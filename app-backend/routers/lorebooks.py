from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.orm import Session
import json

from core.database import get_db
from core import models
from services.parse_lorebook import parse_sillytavern_lorebook
from schemas import LorebookCreate, LorebookUpdate

router = APIRouter()

@router.post("/import")
def import_lorebook(file: UploadFile = File(...), db: Session = Depends(get_db)):
    """
    导入并解析 SillyTavern 格式的世界书 JSON 文件，保存到数据库中。
    """
    try:
        content = file.file.read().decode("utf-8")
        raw_data = json.loads(content)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"文件格式错误，必须是有效的 JSON 文件: {str(e)}")

    try:
        parsed_data = parse_sillytavern_lorebook(raw_data)
        
        # 将 entries 列表序列化为 JSON 字符串存储
        entries_str = json.dumps(parsed_data["entries"], ensure_ascii=False)
        
        new_lorebook = models.Lorebook(
            name=parsed_data["name"],
            description=parsed_data["description"],
            scan_depth=parsed_data["scan_depth"],
            token_budget=parsed_data["token_budget"],
            recursive_scanning=parsed_data["recursive_scanning"],
            entries=entries_str
        )
        db.add(new_lorebook)
        db.commit()
        db.refresh(new_lorebook)
        
        return {
            "message": "Lorebook imported successfully",
            "lorebook_id": new_lorebook.id,
            "name": new_lorebook.name,
            "entries_count": len(parsed_data["entries"])
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"解析世界书失败: {str(e)}")

@router.get("")
def list_lorebooks(db: Session = Depends(get_db)):
    """
    获取系统中所有独立世界书的列表
    """
    lorebooks = db.query(models.Lorebook).all()
    result = []
    for lb in lorebooks:
        entries_count = 0
        if lb.entries:
            try:
                entries_count = len(json.loads(lb.entries))
            except Exception:
                pass
        result.append({
            "id": lb.id,
            "name": lb.name,
            "description": lb.description or "",
            "scan_depth": lb.scan_depth,
            "token_budget": lb.token_budget,
            "recursive_scanning": lb.recursive_scanning,
            "entries_count": entries_count,
            "created_at": lb.created_at.isoformat() if lb.created_at else None
        })
    return {"lorebooks": result}

@router.get("/{lorebook_id}")
def get_lorebook_detail(lorebook_id: int, db: Session = Depends(get_db)):
    """
    获取单个世界书的完整详情（包含所有条目）
    """
    lb = db.get(models.Lorebook, lorebook_id)
    if not lb:
        raise HTTPException(status_code=404, detail="Lorebook not found")
        
    entries_list = []
    if lb.entries:
        try:
            entries_list = json.loads(lb.entries)
        except Exception:
            pass
            
    return {
        "id": lb.id,
        "name": lb.name,
        "description": lb.description or "",
        "scan_depth": lb.scan_depth,
        "token_budget": lb.token_budget,
        "recursive_scanning": lb.recursive_scanning,
        "entries": entries_list,
        "created_at": lb.created_at.isoformat() if lb.created_at else None
    }

@router.put("/{lorebook_id}")
def update_lorebook(lorebook_id: int, lb_data: LorebookUpdate, db: Session = Depends(get_db)):
    """
    编辑并更新独立世界书的属性和条目
    """
    lb = db.get(models.Lorebook, lorebook_id)
    if not lb:
        raise HTTPException(status_code=404, detail="Lorebook not found")
        
    if lb_data.name is not None:
        lb.name = lb_data.name
    if lb_data.description is not None:
        lb.description = lb_data.description
    if lb_data.scan_depth is not None:
        lb.scan_depth = lb_data.scan_depth
    if lb_data.token_budget is not None:
        lb.token_budget = lb_data.token_budget
    if lb_data.recursive_scanning is not None:
        lb.recursive_scanning = lb_data.recursive_scanning
    if lb_data.entries is not None:
        # 将传入的 Pydantic 模型列表转换为字典列表后序列化为 JSON 字符串
        entries_dict_list = [entry.dict() for entry in lb_data.entries]
        lb.entries = json.dumps(entries_dict_list, ensure_ascii=False)
        
    db.commit()
    db.refresh(lb)
    
    entries_count = 0
    if lb.entries:
        try:
            entries_count = len(json.loads(lb.entries))
        except Exception:
            pass
            
    return {
        "message": "Lorebook updated successfully",
        "lorebook_id": lb.id,
        "name": lb.name,
        "entries_count": entries_count
    }

@router.delete("/{lorebook_id}")
@router.post("/{lorebook_id}/delete")
def delete_lorebook(lorebook_id: int, db: Session = Depends(get_db)):
    """
    删除指定的独立世界书，这会级联清除角色-世界书关联表中的数据。
    """
    lb = db.get(models.Lorebook, lorebook_id)
    if not lb:
        raise HTTPException(status_code=404, detail="Lorebook not found")
        
    db.delete(lb)
    db.commit()
    
    return {
        "message": "Lorebook deleted successfully",
        "lorebook_id": lorebook_id
    }

@router.post("/characters/{character_id}/bind/{lorebook_id}")
def bind_lorebook(character_id: int, lorebook_id: int, db: Session = Depends(get_db)):
    """
    将世界书绑定到指定角色卡
    """
    char = db.get(models.Character, character_id)
    if not char:
        raise HTTPException(status_code=404, detail="Character not found")
        
    lb = db.get(models.Lorebook, lorebook_id)
    if not lb:
        raise HTTPException(status_code=404, detail="Lorebook not found")
        
    if lb not in char.lorebooks:
        char.lorebooks.append(lb)
        db.commit()
        
    return {
        "message": f"Successfully bound lorebook '{lb.name}' to character '{char.name}'",
        "character_id": character_id,
        "lorebook_id": lorebook_id
    }

@router.post("/characters/{character_id}/unbind/{lorebook_id}")
def unbind_lorebook(character_id: int, lorebook_id: int, db: Session = Depends(get_db)):
    """
    将世界书与指定角色卡解绑
    """
    char = db.get(models.Character, character_id)
    if not char:
        raise HTTPException(status_code=404, detail="Character not found")
        
    lb = db.get(models.Lorebook, lorebook_id)
    if not lb:
        raise HTTPException(status_code=404, detail="Lorebook not found")
        
    if lb in char.lorebooks:
        char.lorebooks.remove(lb)
        db.commit()
        
    return {
        "message": f"Successfully unbound lorebook '{lb.name}' from character '{char.name}'",
        "character_id": character_id,
        "lorebook_id": lorebook_id
    }
