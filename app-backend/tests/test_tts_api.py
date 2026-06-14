import os
import sys
import time
import asyncio

# 将当前目录的父目录加入系统路径以确保能正常导入 core 和 services
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.tts_service import TTSService
from core.config import settings

async def async_test():
    tts_service = TTSService.get_instance()
    
    test_text_async = "*叹了口气，有些伤心地低下头* 唉，今天在学校真的好累啊。 *轻声笑了笑* 不过，只要一见到你，我所有的疲惫就全部烟消云散啦！"
    voice = "冰糖"
    
    print("\n=================== 异步 TTS 测试 ===================")
    print("--- 首次合成测试 (发送 API 请求) ---")
    start_time = time.time()
    try:
        audio_url = await tts_service.generate_speech_async(test_text_async, voice=voice, speed=1.0)
        duration = time.time() - start_time
        print(f"[SUCCESS] 异步首次合成成功！")
        print(f"音频 URL: {audio_url}")
        print(f"耗时: {duration:.2f} 秒")
        
        # 验证文件是否存在且不为空
        filename = os.path.basename(audio_url)
        filepath = os.path.join(settings.TTS_CACHE_DIR, filename)
        if os.path.exists(filepath):
            filesize = os.path.getsize(filepath)
            print(f"物理路径: {filepath}")
            print(f"大小: {filesize / 1024:.2f} KB")
        else:
            print("[ERROR] 未找到合成的音频文件！")
            return
            
    except Exception as e:
        print(f"[ERROR] 异步首次合成发生异常: {e}")
        import traceback
        traceback.print_exc()
        return

    print("\n--- 第二次合成测试 (验证缓存命中) ---")
    start_time = time.time()
    try:
        audio_url_2 = await tts_service.generate_speech_async(test_text_async, voice=voice, speed=1.0)
        duration_2 = time.time() - start_time
        print(f"[SUCCESS] 异步第二次合成成功！")
        print(f"音频 URL: {audio_url_2}")
        print(f"缓存命中耗时: {duration_2 * 1000:.2f} 毫秒")
        
        if audio_url == audio_url_2:
            print("[SUCCESS] 缓存路径匹配成功！")
        else:
            print("[ERROR] 缓存路径不一致！")
            
    except Exception as e:
        print(f"[ERROR] 异步缓存测试发生异常: {e}")

async def async_preprocess_test():
    print("\n=================== LLM 预处理器测试 ===================")
    tts_service = TTSService.get_instance()
    
    test_cases = [
        "她似乎有些委屈的撒娇",
        "*她咬了咬下唇，有些委屈地撒娇* \"你...你昨天怎么没来找我嘛...\" *拉扯着你的衣袖*",
        "我没事。（叹了口气）只是有点累了。",
        "*开心得跳起来* \"真的吗？太好了！\"（笑声）",
        "今天天气真好。",
        "她微微一笑说道：“你终于来啦。”",
        "我有些不好意思地低下头。其实...我也很想你。",
        "【摸摸头】别伤心了，有我在呢。",
        "（叹了口气） 唉，今天在学校真的好累啊。 [吸气] 不过，只要一见到你，我所有的疲惫就全部烟消云散啦！"
    ]
    
    for i, case in enumerate(test_cases, 1):
        print(f"\n--- 测试案例 {i} ---")
        print(f"输入: {case}")
        start_time = time.time()
        output = await tts_service.preprocess_roleplay_text_llm(case)
        duration = time.time() - start_time
        print(f"输出: {output}")
        print(f"耗时: {duration:.2f} 秒")

def main():
    print("=================== 同步 TTS 测试 ===================")
    print(f"TTS 状态: {'启用' if settings.TTS_ENABLED else '禁用'}")
    print(f"API 基础 URL: {settings.TTS_MIMO_BASE_URL}")
    print(f"模型名称: {settings.TTS_MIMO_MODEL}")
    print(f"默认音色: {settings.TTS_DEFAULT_VOICE}")
    print(f"缓存路径: {settings.TTS_CACHE_DIR}")
    
    # 运行预处理器单元测试
    asyncio.run(async_preprocess_test())
    
    # 获取单例
    tts_service = TTSService.get_instance()
    
    test_text_sync = "（微笑着向你招手） 嗨！好久不见啦！（激动） 你今天过得怎么样？"
    voice = "冰糖"
    
    print("\n--- 首次合成测试 (发送 API 请求) ---")
    start_time = time.time()
    try:
        audio_url = tts_service.generate_speech_sync(test_text_sync, voice=voice, speed=1.0)
        duration = time.time() - start_time
        print(f"[SUCCESS] 首次合成成功！")
        print(f"音频 URL: {audio_url}")
        print(f"耗时: {duration:.2f} 秒")
        
        # 验证文件是否存在且不为空
        filename = os.path.basename(audio_url)
        filepath = os.path.join(settings.TTS_CACHE_DIR, filename)
        if os.path.exists(filepath):
            filesize = os.path.getsize(filepath)
            print(f"物理路径: {filepath}")
            print(f"大小: {filesize / 1024:.2f} KB")
        else:
            print("[ERROR] 未找到合成的音频文件！")
            return
            
    except Exception as e:
        print(f"[ERROR] 首次合成发生异常: {e}")
        import traceback
        traceback.print_exc()
        return

    print("\n--- 第二次合成测试 (验证缓存命中) ---")
    start_time = time.time()
    try:
        audio_url_2 = tts_service.generate_speech_sync(test_text_sync, voice=voice, speed=1.0)
        duration_2 = time.time() - start_time
        print(f"[SUCCESS] 第二次合成成功！")
        print(f"音频 URL: {audio_url_2}")
        print(f"缓存命中耗时: {duration_2 * 1000:.2f} 毫秒")
        
        if audio_url == audio_url_2:
            print("[SUCCESS] 缓存路径匹配成功！")
        else:
            print("[ERROR] 缓存路径不一致！")
            
    except Exception as e:
        print(f"[ERROR] 缓存测试发生异常: {e}")

    # 运行异步测试
    asyncio.run(async_test())
    
    # 运行数据库绑定与自愈重建测试
    asyncio.run(async_db_bound_test())
    print("\n=================== 测试全部完成 ===================")

async def async_db_bound_test():
    from core.database import SessionLocal
    from core.models import ChatMessage, MessageRole, Session as DbSession, SessionPersona, Character
    import os
    
    print("\n=================== 数据库绑定与自愈重建 TTS 测试 ===================")
    db = SessionLocal()
    try:
        # 1. 模拟或获取一个 Character, Session 和 SessionPersona
        char = db.query(Character).first()
        if not char:
            # 创建临时 Character 用于测试
            char = Character(name="测试小助手", description="这是一个测试人设", first_mes="你好呀")
            db.add(char)
            db.commit()
            db.refresh(char)
            
        session = db.query(DbSession).first()
        if not session:
            session = DbSession(title="测试会话")
            db.add(session)
            db.commit()
            db.refresh(session)
            
        persona = db.query(SessionPersona).filter(SessionPersona.session_id == session.id).first()
        if not persona:
            persona = SessionPersona(session_id=session.id, character_id=char.id)
            db.add(persona)
            db.commit()
            db.refresh(persona)
            
        # 2. 插入一条测试 Assistant 消息
        test_content = "*撒娇* 你今天怎么才来呀！我等你好久了。"
        msg = ChatMessage(
            session_id=session.id,
            role=MessageRole.assistant,
            content=test_content,
            is_active=True
        )
        db.add(msg)
        db.commit()
        db.refresh(msg)
        
        print(f"[INFO] 成功创建测试消息 ID={msg.id}, content='{msg.content}'")
        
        tts_service = TTSService.get_instance()
        voice = "冰糖"
        
        # 3. 首次调用数据库绑定合成
        print("\n--- 首次数据库绑定合成测试 ---")
        start_time = time.time()
        audio_url = await tts_service.generate_speech_async(
            text="", # 绑定模式下，text 可以不传或传入空，会自动拉取数据库中的消息内容
            voice=voice,
            speed=1.0,
            message_id=msg.id,
            db=db
        )
        duration = time.time() - start_time
        print(f"[SUCCESS] 首次绑定合成成功！")
        print(f"音频 URL: {audio_url}")
        print(f"耗时: {duration:.2f} 秒")
        
        # 验证数据库是否回写
        db.refresh(msg)
        print(f"数据库记录中的 audio_path: {msg.audio_path}")
        assert msg.audio_path == audio_url, "数据库 audio_path 回写不匹配！"
        
        # 验证物理文件是否存在
        filename = os.path.basename(audio_url)
        filepath = os.path.join(settings.TTS_CACHE_DIR, filename)
        assert os.path.exists(filepath), "合成的物理音频文件不存在！"
        print(f"物理文件存在: {filepath}, 大小: {os.path.getsize(filepath) / 1024:.2f} KB")
        
        # 4. 第二次调用（验证缓存秒开）
        print("\n--- 第二次绑定合成测试 (验证缓存命中) ---")
        start_time = time.time()
        audio_url_2 = await tts_service.generate_speech_async(
            text="",
            voice=voice,
            speed=1.0,
            message_id=msg.id,
            db=db
        )
        duration_2 = time.time() - start_time
        print(f"[SUCCESS] 第二次绑定合成成功！")
        print(f"缓存命中音频 URL: {audio_url_2}")
        print(f"缓存命中耗时: {duration_2 * 1000:.2f} 毫秒")
        assert audio_url_2 == audio_url, "两次返回的 URL 不一致！"
        assert duration_2 < 0.05, f"缓存命中耗时过长 ({duration_2:.4f}s)，可能触发了重新合成！"
        
        # 5. 模拟被 LRU 清理：物理删除文件
        print("\n--- 模拟 LRU 被动清理后重建自愈测试 ---")
        if os.path.exists(filepath):
            os.remove(filepath)
            print(f"[INFO] 已物理删除文件: {filepath}")
        assert not os.path.exists(filepath), "物理文件删除失败！"
        
        start_time = time.time()
        audio_url_3 = await tts_service.generate_speech_async(
            text="",
            voice=voice,
            speed=1.0,
            message_id=msg.id,
            db=db
        )
        duration_3 = time.time() - start_time
        print(f"[SUCCESS] 自愈重建成功！")
        print(f"重建后的音频 URL: {audio_url_3}")
        print(f"重建耗时: {duration_3:.2f} 秒")
        assert audio_url_3 == audio_url, "重建后 URL 发生改变！"
        assert os.path.exists(filepath), "重建物理文件未生成！"
        
        # 6. 验证“重新生成消息”下记忆提取和认知更新的过滤机制
        print("\n--- 重新生成消息(Inactive)过滤机制测试 ---")
        # 插入一条 Inactive 的废弃候选 Assistant 消息
        inactive_msg = ChatMessage(
            session_id=session.id,
            role=MessageRole.assistant,
            content="这是一条被废弃的候选消息，绝对不应该被提纯入库！",
            is_active=False
        )
        db.add(inactive_msg)
        db.commit()
        db.refresh(inactive_msg)
        print(f"[INFO] 成功插入 Inactive 消息 ID={inactive_msg.id}")
        
        # 测试记忆提纯
        from services.cognition_service import get_unsummarized_count
        unsummarized_cnt = get_unsummarized_count(session.id, db)
        print(f"未总结消息数 (已过滤 Inactive): {unsummarized_cnt}")
        
        # 清理测试数据
        db.delete(msg)
        db.delete(inactive_msg)
        db.commit()
        print("[SUCCESS] 临时测试消息已从数据库清理。")
        
    except Exception as e:
        print(f"[ERROR] 数据库绑定/自愈测试失败: {e}")
        import traceback
        traceback.print_exc()
        raise e
    finally:
        db.close()

if __name__ == "__main__":
    main()
