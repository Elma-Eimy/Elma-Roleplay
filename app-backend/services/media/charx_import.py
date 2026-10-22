"""受限 CHARX 预览与显式导入；不执行模块、不访问素材外链。"""
import base64
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import tempfile
import threading
import time
import uuid
import warnings
import zipfile
import zlib

from PIL import Image, ImageOps
from sqlalchemy import text
from core.config import settings
from core.models import Character, CharacterPortrait, CharacterPackageImport, OutboxJob
from services.character_service import _apply_character_data
from services.media.charx_plan import build_card_plan

MB = 1024 * 1024
MAX_EXPANDED = 60 * MB
MAX_IMAGE = 8 * MB
MAX_CARD = 2 * MB
MAX_FILES = 1000
MAX_IMAGES = 300
MAX_STAGED_BYTES = 60 * MB
MAX_TOTAL_PIXELS = 250_000_000
TTL = 15 * 60
MAX_PREVIEWS = 3
ROOT = Path(tempfile.gettempdir()) / ("ai-roleplay-charx-" + hashlib.sha256(str(settings.STORAGE_SQLITE_DB_PATH).encode()).hexdigest()[:16])
LOCK = threading.RLock()
ACTIVE = set()


class CharxConflict(ValueError):
    pass


class CharxLimit(ValueError):
    pass


def upload_limit():
    # 此入口独立配置；即使手工配置异常，也不允许退化为无限制上传。
    return max(1, min(100, settings.SECURITY_MAX_CHARX_SIZE_MB)) * MB


def _directory(token):
    if not re.fullmatch(r"[0-9a-f]{32}", token):
        raise LookupError("预览不存在或已过期，请重新上传")
    directory = ROOT / token
    if directory.is_symlink() or directory.resolve().parent != ROOT.resolve():
        raise LookupError("无效的预览路径")
    return directory


def _remove(token, status=None):
    directory = _directory(token)
    if directory.exists():
        shutil.rmtree(directory)
        if status:
            (ROOT / f'{token}.state').write_text(json.dumps({'status': status, 'expires_at': time.time() + TTL}), encoding='utf-8')


def _cleanup():
    ROOT.mkdir(parents=True, exist_ok=True)
    now = time.time()
    for directory in ROOT.iterdir():
        if directory.suffix == '.state' and now - directory.stat().st_mtime > TTL:
            directory.unlink(missing_ok=True)
            continue
        if directory.is_dir() and re.fullmatch(r"[0-9a-f]{32}", directory.name):
            if directory.name not in ACTIVE and now - directory.stat().st_mtime > TTL:
                _remove(directory.name, 'expired')


def cleanup_previews():
    with LOCK:
        _cleanup()


def _manifest(token):
    directory = _directory(token)
    try:
        value = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        raise LookupError("预览不存在或已过期，请重新上传") from exc
    if time.time() >= value["expires_at"] or value.get('plan_version') != 1:
        _remove(token, 'expired')
        raise LookupError("预览已过期，请重新上传")
    return value


def cancel_preview(token):
    with LOCK:
        _remove(token, 'cancelled')
    return {"message": "预览已清理"}


def preview_status(token, db):
    with LOCK:
        _directory(token)
        receipt = db.get(CharacterPackageImport, token)
        if receipt:
            if receipt.character_id is None or db.get(Character, receipt.character_id) is None:
                return {'status': 'target_deleted'}
            return {'status': 'imported', 'result': json.loads(receipt.result_json)}
        if token in ACTIVE:
            return {'status': 'parsing'}
        try:
            value = _manifest(token)
            return {'status': 'ready', 'expires_at': value['expires_at']}
        except LookupError:
            state = ROOT / f'{token}.state'
            if state.exists():
                value = json.loads(state.read_text(encoding='utf-8'))
                if time.time() < value['expires_at']:
                    return {'status': value['status']}
            return {'status': 'not_found'}


def _safe_path(name):
    path = PurePosixPath(name)
    if not name or "\\" in name or ":" in name or "\x00" in name or path.is_absolute() or any(part in (".", "..", "") for part in name.rstrip("/").split("/")):
        raise ValueError("角色包包含不安全的文件路径")
    return name


def _read(archive, info, maximum):
    with archive.open(info) as source:
        data = source.read(maximum + 1)
    if len(data) > maximum or len(data) != info.file_size:
        raise ValueError("角色包文件超过限制或长度不完整")
    return data


def _image(content, reserve_pixels):
    with warnings.catch_warnings():
        warnings.simplefilter("error", Image.DecompressionBombWarning)
        with Image.open(io.BytesIO(content)) as image:
            extension = {"PNG": "png", "JPEG": "jpg", "WEBP": "webp"}.get(image.format)
            pixels = image.width * image.height
            if not extension or image.width * image.height > 25_000_000 or getattr(image, "n_frames", 1) > 1:
                raise ValueError("首版仅导入 2500 万像素以内的静态 PNG/JPEG/WebP")
            # 在校验和解码前占用预算；损坏图片失败后也不能返还已尝试的工作量。
            reserve_pixels(pixels)
            image.verify()
        with Image.open(io.BytesIO(content)) as image:
            image.load()
            with ImageOps.exif_transpose(image) as oriented:
                oriented.thumbnail((128, 160))
                output = io.BytesIO()
                oriented.convert("RGBA").save(output, format="PNG")
    return extension, base64.b64encode(output.getvalue()).decode("ascii")


def preview_package(content):
    if len(content) > upload_limit():
        raise ValueError("角色包超过上传大小限制")
    with LOCK:
        _cleanup()
        if sum(1 for p in ROOT.iterdir() if p.is_dir()) >= MAX_PREVIEWS:
            raise CharxConflict("未完成的预览过多，请关闭其他预览，或等待 15 分钟后重试")
        token = uuid.uuid4().hex
        directory = _directory(token)
        directory.mkdir()
        ACTIVE.add(token)
    # 解压和像素解码不能占用全局生命周期锁。
    try:
        result = _parse_archive(content, directory)
        result.update(token=token, status='ready', plan_version=1, package_sha256=hashlib.sha256(content).hexdigest(), expires_at=time.time() + TTL)
        with LOCK:
            (directory / "manifest.json").write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
        return result
    except (zipfile.BadZipFile, zlib.error) as exc:
        with LOCK:
            _remove(token)
        raise ValueError("压缩包已损坏或解压校验失败") from exc
    except Exception:
        with LOCK:
            _remove(token)
        raise
    finally:
        with LOCK:
            ACTIVE.discard(token)


def _parse_archive(content, directory):
    try:
        archive = zipfile.ZipFile(io.BytesIO(content))
    except zipfile.BadZipFile as exc:
        raise ValueError("不是有效的 CHARX/ZIP 角色包") from exc
    with archive:
        infos = archive.infolist()
        if len(infos) > MAX_FILES or sum(item.file_size for item in infos) > MAX_EXPANDED:
            raise ValueError("角色包最多 1000 个文件，解压后总大小不得超过 60 MB")
        names = {}
        folded = set()
        for item in infos:
            _safe_path(item.orig_filename)
            if Path(item.filename).suffix.lower() in (".zip", ".charx", ".rar", ".7z"):
                raise ValueError("首版不接受包含嵌套压缩包的角色包")
            if item.filename.casefold() in folded or stat.S_ISLNK(item.external_attr >> 16):
                raise ValueError("角色包包含重复路径或符号链接")
            if item.flag_bits & 1 or item.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED):
                raise ValueError("首版不支持加密包或此压缩方式")
            folded.add(item.filename.casefold())
            names[item.filename] = item
        if "card.json" not in names or names["card.json"].file_size > MAX_CARD:
            raise ValueError("角色包根目录须包含不超过 2 MB 的 card.json")
        try:
            raw = json.loads(_read(archive, names["card.json"], MAX_CARD).decode("utf-8-sig"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise ValueError("card.json 不是有效的 UTF-8 JSON") from exc
        if not isinstance(raw, dict) or not isinstance(raw.get("data"), dict) or raw.get("spec") != "chara_card_v3" or raw.get("spec_version") != "3.0":
            raise ValueError("首版仅支持 CCv3 3.0 角色包")
        data = raw["data"]
        if data.get("extensions") is not None and not isinstance(data["extensions"], dict):
            raise ValueError("角色扩展必须是 JSON 对象")
        book = data.get("character_book")
        if book is not None and (not isinstance(book, dict) or not isinstance(book.get("entries", []), list) or any(not isinstance(entry, dict) for entry in book.get("entries", []))):
            raise ValueError("内嵌世界书结构无效")
        plan = build_card_plan(raw)
        card = plan['card']
        resources = data.get("assets", [])
        if not isinstance(resources, list) or len(resources) > MAX_FILES:
            raise ValueError("素材清单无效或超过 1000 项")
        notices = ["仅导入角色设定与选中的静态图片；不开启情绪、换装或开场自动切换。"]
        if "module.risum" in names:
            notices.append("包含 RisuAI 模块：正则、触发器及模块内世界书未导入，原平台效果不会完整还原。")
        if data.get("nickname") or data.get("group_only_greetings"):
            notices.append("昵称替代与群聊专用开场语义暂不支持。")
        if re.search(r"<img\b|<img=|\{\{(?:getvar|setvar|equal)::", json.dumps(data, ensure_ascii=False), re.I):
            notices.append("包含行内图片或变量界面，阅读文本会简化；内嵌图片和界面暂不还原。")
        if (data.get('extensions') or {}).get("risuai"):
            notices.append("RisuAI 专用扩展仅留作来源提示，不导入执行。")
        # 仅保留当前应用认识的内嵌世界书，模块文件不会被装配执行。
        assets = []
        staged_bytes = 0
        decoded_pixels = 0

        def reserve_pixels(pixels):
            nonlocal decoded_pixels
            if decoded_pixels + pixels > MAX_TOTAL_PIXELS:
                raise CharxLimit("角色包图片总像素超过 2.5 亿，请减少素材")
            decoded_pixels += pixels

        skipped = 0
        checked = {"card.json"}
        cache = {}
        skipped_assets = []

        def skip(descriptor, reason):
            nonlocal skipped
            skipped += 1
            skipped_assets.append({'name': descriptor['name'], 'reason': reason})
        for index, descriptor in enumerate(resources):
            if not isinstance(descriptor, dict) or any(not isinstance(descriptor.get(key), str) for key in ("type", "name", "uri", "ext")):
                raise ValueError("素材清单条目缺少有效的 type/name/uri/ext")
            uri = descriptor["uri"]
            if max(len(descriptor[key]) for key in ("type", "name", "uri", "ext")) > 2048:
                raise ValueError("素材描述字段过长")
            if not uri.startswith("embeded://"):
                skip(descriptor, '外链或不支持的 URI；未访问网络')
                continue
            source_name = _safe_path(uri[len("embeded://"):])
            info = names.get(source_name)
            if info is None or info.is_dir() or info.file_size > MAX_IMAGE:
                skip(descriptor, '引用缺失、不是文件或超过单图大小限制')
                continue
            if descriptor["ext"].lower() not in ("png", "jpg", "jpeg", "webp"):
                skip(descriptor, '不是支持的静态图片类型')
                continue
            if source_name not in cache:
                # 读取前预留字节预算，失败不返还；同一条目成功或失败都只处理一次。
                if staged_bytes + info.file_size > MAX_STAGED_BYTES:
                    raise CharxLimit("尝试处理的图片总大小超过 60 MB")
                staged_bytes += info.file_size
                image_data = _read(archive, info, MAX_IMAGE)
                checked.add(source_name)
                try:
                    extension, thumbnail = _image(image_data, reserve_pixels)
                except CharxLimit:
                    raise
                except (ValueError, OSError, SyntaxError, Image.DecompressionBombError, Image.DecompressionBombWarning):
                    cache[source_name] = None
                else:
                    (directory / f"{index}.{extension}").write_bytes(image_data)
                    (directory / f"{index}.thumb").write_text(thumbnail, encoding="ascii")
                    cache[source_name] = (extension, index, hashlib.sha256(image_data).hexdigest())
            if cache[source_name] is None:
                skip(descriptor, '损坏、动态或像素超限的图片')
                continue
            if len(assets) >= MAX_IMAGES:
                raise ValueError("首版最多预览 300 张可用图片")
            extension, storage_index, digest = cache[source_name]
            assets.append({"index": index, "name": descriptor["name"], "type": descriptor["type"], "uri": uri,
                           "ext": extension, 'storage_index': storage_index, 'sha256': digest})
        # 对未导入的 ZIP 条目也执行有界流读取与 CRC 检查，不能信任清单长度。
        for name, info in names.items():
            if name in checked or info.is_dir():
                continue
            consumed = 0
            with archive.open(info) as source:
                while block := source.read(MB):
                    consumed += len(block)
                    if consumed > info.file_size or consumed > MAX_EXPANDED:
                        raise ValueError("角色包实际解压大小超过限制")
        if skipped:
            notices.append(f"{skipped} 项素材未导入：可能为缺失引用、外链、非静态图片、损坏图片或单图超过 8 MB。")
        plan['compatibility'].append({'status': 'preserved', 'label': '可选静态图片', 'count': len(assets)})
        plan['compatibility'].append({'status': 'skipped', 'label': '跳过的素材引用', 'count': skipped})
        unreferenced = sum(not info.is_dir() and name != 'card.json' and name not in checked for name, info in names.items())
        if unreferenced:
            plan['compatibility'].append({'status': 'skipped', 'label': '未导入的包内文件（含模块、非图片和未引用文件）', 'count': unreferenced})
        return {**plan, "assets": assets, "warnings": notices, "skipped_count": skipped, 'skipped_assets': skipped_assets}


def preview_images(token, offset=0, limit=12):
    with LOCK:
        value = _manifest(token)
        images = []
        for asset in value["assets"][offset:offset + limit]:
            thumbnail = (_directory(token) / f"{asset['storage_index']}.thumb").read_text(encoding="ascii")
            images.append({"index": asset["index"], "thumbnail": "data:image/png;base64," + thumbnail})
        return {"images": images, "has_more": offset + limit < len(value["assets"])}


def _existing_image(path, root, known_digest=None):
    """仅对受管理目录内仍存在的旧资源计算摘要，不读取卡片指定的任意路径。"""
    if not path:
        return None
    candidate = Path(path).resolve()
    if not candidate.is_relative_to(root.resolve()) or not candidate.is_file():
        return None
    if candidate.stat().st_size > 100 * MB:
        return None
    if known_digest:
        return known_digest
    with candidate.open('rb') as source:
        digest = hashlib.file_digest(source, 'sha256').hexdigest()
    return digest


def import_package(token, request, db):
    fingerprint = hashlib.sha256(json.dumps({**request, "portrait_indices": sorted(request["portrait_indices"])}, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    paths = []
    with LOCK:
        _directory(token)
        try:
            db.execute(text("BEGIN IMMEDIATE"))
            receipt = db.get(CharacterPackageImport, token)
            if receipt:
                if receipt.request_hash != fingerprint or receipt.character_id is None or db.get(Character, receipt.character_id) is None:
                    raise CharxConflict("此预览已用于其他导入，或导入的角色已删除")
                result = json.loads(receipt.result_json)
                db.rollback()
                return result
            value = _manifest(token)
            assets = {asset["index"]: asset for asset in value["assets"]}
            selected = set(request["portrait_indices"])
            avatar = request["avatar_index"]
            if not selected.issubset(assets) or (avatar is not None and avatar not in assets):
                raise ValueError("所选素材不存在或不受支持")
            target = request["character_id"]
            operation = 'create_character' if target is None else 'append_assets'
            if request.get('operation') not in (None, operation):
                raise ValueError('操作类型与目标角色不匹配')
            if target is not None:
                character = db.get(Character, target)
                if character is None:
                    raise LookupError("目标角色不存在")
            else:
                card = dict(value["card"])
                name = (request["name"] or card["name"]).strip()
                if not name or len(name) > 50 or any(ord(c) < 32 for c in name):
                    raise ValueError("新角色名称须为 1–50 字")
                if db.query(Character.id).filter_by(name=name).first():
                    raise CharxConflict("已有同名角色，请改名后新建，或从已有角色档案补充图片")
                card.update(name=name, avatar_path="")
                character = Character()
                _apply_character_data(character, card)
                db.add(character)
                db.flush()
            root = Path(settings.STORAGE_UPLOAD_AVATAR_DIR)
            root.mkdir(parents=True, exist_ok=True)
            existing = {}
            for portrait in db.query(CharacterPortrait).filter_by(character_id=character.id).all():
                digest = _existing_image(portrait.image_path, root, portrait.content_sha256)
                if digest:
                    portrait.content_sha256 = digest
                    existing[digest] = portrait.image_path
            portrait_hashes = set(existing)
            avatar_hash = _existing_image(character.avatar_path, root)
            if avatar_hash:
                existing.setdefault(avatar_hash, character.avatar_path)
            saved = {}
            added = 0
            duplicates = 0
            for index in sorted(selected | ({avatar} if avatar is not None else set())):
                asset = assets[index]
                digest = asset['sha256']
                if digest not in existing:
                    destination = root / f"portrait_{uuid.uuid4().hex}.{asset['ext']}"
                    paths.append(destination)
                    shutil.copyfile(_directory(token) / f"{asset['storage_index']}.{asset['ext']}", destination)
                    existing[digest] = destination.as_posix()
                saved[index] = existing[digest]
                if index in selected:
                    if request.get('skip_duplicates', True) and digest in portrait_hashes:
                        duplicates += 1
                        continue
                    display_name = "".join(c for c in asset["name"] if ord(c) >= 32).strip()[:80] or "立绘"
                    db.add(CharacterPortrait(character_id=character.id, name=display_name,
                                             image_path=saved[index], source_type=asset["type"][:100],
                                             source_name=asset["name"], source_uri=asset["uri"], content_sha256=digest))
                    portrait_hashes.add(digest)
                    added += 1
            if avatar is not None:
                if character.avatar_path and character.avatar_path != saved[avatar]:
                    db.add(OutboxJob(task_type="delete_avatar", payload=json.dumps({"file_path": character.avatar_path})))
                character.avatar_path = saved[avatar]
            result = {"character_id": character.id, "created": target is None, "portraits_added": added,
                      'duplicates_skipped': duplicates, 'operation': operation, 'package_sha256': value['package_sha256']}
            db.add(CharacterPackageImport(token=token, request_hash=fingerprint, character_id=character.id, result_json=json.dumps(result)))
            db.commit()
        except Exception:
            db.rollback()
            for path in paths:
                path.unlink(missing_ok=True)
            raise
        # 回执与资源已在同一事务提交；临时清理失败不能将成功导入报告为失败。
        try:
            _remove(token)
        except OSError:
            pass
        return result
