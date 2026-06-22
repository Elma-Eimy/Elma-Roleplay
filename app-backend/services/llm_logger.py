import json
import time

def log_llm_non_stream(model_name: str, messages: list, response_raw, elapsed: float):
    """记录非流式大模型请求与原始 HTTP 响应头、状态码，辅助诊断空白字符及报错。"""
    log_file = "llm_debug.log"
    try:
        status_code = response_raw.status_code
        headers = dict(response_raw.headers)
        completion = response_raw.parse()
        msg = completion.choices[0].message
        content = getattr(msg, "content", None) or ""
        reasoning = getattr(msg, "reasoning_content", None) or ""
        
        with open(log_file, "a", encoding="utf-8") as f:
            f.write("\n" + "="*80 + "\n")
            f.write(f"🌐 [NON-STREAM REQUEST] Model: {model_name} | Time: {time.strftime('%Y-%m-%d %H:%M:%S')} | Elapsed: {elapsed:.2f}s\n")
            f.write(f"📥 [HTTP STATUS] {status_code}\n")
            f.write(f"📥 [HEADERS] Trace-ID: {headers.get('x-ds-trace-id', 'N/A')} | Server: {headers.get('server', 'N/A')}\n")
            f.write("--- MESSAGES SENT TO LLM ---\n")
            f.write(json.dumps(messages, ensure_ascii=False, indent=2) + "\n")
            if reasoning:
                f.write("--- RAW REASONING CONTENT ---\n")
                f.write(reasoning + "\n")
            f.write("--- RAW CONTENT ---\n")
            f.write(content + "\n")
            f.write("="*80 + "\n")
    except Exception as e:
        try:
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(f"❌ [NON-STREAM LOG ERROR] Failed to parse and log response: {str(e)}\n")
                f.write("="*80 + "\n")
        except:
            pass

def log_llm_stream_wrapper(stream, model_name: str, messages: list):
    """透明代理流的迭代过程，捕获并向 llm_debug.log 写入每一次 chunk 产生的正文与思考过程。"""
    log_file = "llm_debug.log"
    start_time = time.time()
    
    # 立即记录请求起始部分
    try:
        with open(log_file, "a", encoding="utf-8") as f:
            f.write("\n" + "="*80 + "\n")
            f.write(f"🌐 [STREAM REQUEST] Model: {model_name} | Time: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write("--- MESSAGES SENT TO LLM ---\n")
            f.write(json.dumps(messages, ensure_ascii=False, indent=2) + "\n")
            f.write("----------------------------\n")
    except:
        pass
        
    full_content = []
    full_reasoning = []
    
    try:
        for chunk in stream:
            if chunk.choices and len(chunk.choices) > 0:
                delta = chunk.choices[0].delta
                content_delta = getattr(delta, "content", None) or ""
                reasoning_delta = getattr(delta, "reasoning_content", None) or ""
                
                if content_delta:
                    full_content.append(content_delta)
                if reasoning_delta:
                    full_reasoning.append(reasoning_delta)
            yield chunk
            
        elapsed = time.time() - start_time
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(f"📥 [STREAM RESPONSE COMPLETED] Elapsed: {elapsed:.2f}s\n")
            if full_reasoning:
                f.write("--- RAW REASONING CONTENT ---\n")
                f.write("".join(full_reasoning) + "\n")
            f.write("--- RAW CONTENT ---\n")
            f.write("".join(full_content) + "\n")
            f.write("="*80 + "\n")
    except Exception as e:
        elapsed = time.time() - start_time
        try:
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(f"❌ [STREAM ERROR] Elapsed: {elapsed:.2f}s | Error: {str(e)}\n")
                f.write("="*80 + "\n")
        except:
            pass
        raise e

async def log_llm_stream_wrapper_async(stream, model_name: str, messages: list):
    """透明代理异步流的迭代过程，捕获并向 llm_debug.log 写入每一次 chunk 产生的正文与思考过程。"""
    log_file = "llm_debug.log"
    start_time = time.time()
    
    # 立即记录请求起始部分
    try:
        with open(log_file, "a", encoding="utf-8") as f:
            f.write("\n" + "="*80 + "\n")
            f.write(f"🌐 [STREAM REQUEST] Model: {model_name} | Time: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write("--- MESSAGES SENT TO LLM ---\n")
            f.write(json.dumps(messages, ensure_ascii=False, indent=2) + "\n")
            f.write("----------------------------\n")
    except:
        pass
        
    full_content = []
    full_reasoning = []
    
    try:
        async for chunk in stream:
            if chunk.choices and len(chunk.choices) > 0:
                delta = chunk.choices[0].delta
                content_delta = getattr(delta, "content", None) or ""
                reasoning_delta = getattr(delta, "reasoning_content", None) or ""
                
                if content_delta:
                    full_content.append(content_delta)
                if reasoning_delta:
                    full_reasoning.append(reasoning_delta)
            yield chunk
            
        elapsed = time.time() - start_time
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(f"📥 [STREAM RESPONSE COMPLETED] Elapsed: {elapsed:.2f}s\n")
            if full_reasoning:
                f.write("--- RAW REASONING CONTENT ---\n")
                f.write("".join(full_reasoning) + "\n")
            f.write("--- RAW CONTENT ---\n")
            f.write("".join(full_content) + "\n")
            f.write("="*80 + "\n")
    except Exception as e:
        elapsed = time.time() - start_time
        try:
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(f"❌ [STREAM ERROR] Elapsed: {elapsed:.2f}s | Error: {str(e)}\n")
                f.write("="*80 + "\n")
        except:
            pass
        raise e
