# coding=utf-8
import os
import requests
import base64
import pathlib
import threading
import time
import wave
import dashscope  # DashScope Python SDK 版本需要不低于1.23.9
from dashscope.audio.qwen_tts_realtime import QwenTtsRealtime, QwenTtsRealtimeCallback, AudioFormat

# ======= 常量配置 =======
DEFAULT_TARGET_MODEL = "qwen3-tts-vc-realtime-2026-01-15"  # 声音复刻、语音合成要使用相同的模型
DEFAULT_PREFERRED_NAME = "zhuneishunzi"
DEFAULT_AUDIO_MIME_TYPE = "audio/mpeg"
VOICE_FILE_PATH = "zhuneishunzi.wav"  # 用于声音复刻的本地音频文件的相对路径
VOICE_SUBTITLE = "新幹線のぞみ号、出発！今日もたくさんのお客さんを乗せて走っていくんだ。とっても眺めのいい運転席。スピードは日本一速いんだよ。時速250キロでビュンビュン走るんだ。今日も気をつけて行ってきます！"
OUTPUT_AUDIO_FILE = "output.wav"  # 合成音频输出文件路径

# 预创建的音色 ID（运行 `python tts.py --create-voice` 生成后填入此处）
# VOICE_ID = "qwen-tts-vc-guanyu-voice-20260123174051510-b08e"  # 例如: "cosyvoice-clone-v1-xxxx"
VOICE_ID = "qwen-tts-vc-guanyu-voice-20260202204902188-2ed0"

# TEXT_TO_SYNTHESIZE = [
#     '对吧~我就特别喜欢这种超市，',
#     '尤其是过年的时候',
#     '去逛超市',
#     '就会觉得',
#     '超级超级开心！',
#     '想买好多好多的东西呢！'
# ]
TEXT_TO_SYNTHESIZE = [
'我们，我们学人力资源呐、组织行为学呀、市场营销呀，还有什么呀？嗯，还有一些公共课，对，马克思主义原理。嗨，我都，我都想起点啥呀？哈哈。还有什么英语数学的。嗯，专业课的话，好像还有国际贸易，对，国际贸易实务。',
'嗯，还有什么呢？好像有点不记得了，哈哈哈。哎呦这个脑子真的是。',
'嗯，西方经济学？啊，那个学了学了学了。哎，我怎么能把这个给忘了呢？我们班，我们班主任是教这个的，哈哈，我把我班主任给忘了，哈哈。哎呦这真的，属实不应该啊，属实不应该。',
]

def create_voice(file_path: str,
                 target_model: str = DEFAULT_TARGET_MODEL,
                 preferred_name: str = DEFAULT_PREFERRED_NAME,
                 audio_mime_type: str = DEFAULT_AUDIO_MIME_TYPE,
                 text: str = None):
    """
    创建音色，并返回 voice 参数
    """
    # 新加坡和北京地域的API Key不同。获取API Key：https://help.aliyun.com/zh/model-studio/get-api-key
    # 若没有配置环境变量，请用百炼API Key将下行替换为：api_key = "sk-xxx"
    api_key = os.environ.get("DASHSCOPE_API_KEY", "")

    file_path_obj = pathlib.Path(file_path)
    if not file_path_obj.exists():
        raise FileNotFoundError(f"音频文件不存在: {file_path}")

    base64_str = base64.b64encode(file_path_obj.read_bytes()).decode()
    data_uri = f"data:{audio_mime_type};base64,{base64_str}"

    # 以下为北京地域url，若使用新加坡地域的模型，需将url替换为：https://dashscope-intl.aliyuncs.com/api/v1/services/audio/tts/customization
    url = "https://dashscope-intl.aliyuncs.com/api/v1/services/audio/tts/customization"
    payload = {
        "model": "qwen-voice-enrollment", # 不要修改该值
        "workspace": "ws-9ek0jb22sh2thuil",
        "input": {
            "action": "create",
            "target_model": target_model,
            "preferred_name": preferred_name,
            "audio": {"data": data_uri},
            "text": text
        }
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

    resp = requests.post(url, json=payload, headers=headers)
    if resp.status_code != 200:
        raise RuntimeError(f"创建 voice 失败: {resp.status_code}, {resp.text}")

    try:
        return resp.json()["output"]["voice"]
    except (KeyError, ValueError) as e:
        raise RuntimeError(f"解析 voice 响应失败: {e}")

def init_dashscope_api_key():
    """
    初始化 dashscope SDK 的 API key
    """
    # 新加坡和北京地域的API Key不同。获取API Key：https://help.aliyun.com/zh/model-studio/get-api-key
    # 若没有配置环境变量，请用百炼API Key将下行替换为：dashscope.api_key = "sk-xxx"
    dashscope.api_key = os.environ.get("DASHSCOPE_API_KEY", "")

# ======= 回调类 =======
class MyCallback(QwenTtsRealtimeCallback):
    """
    自定义 TTS 流式回调，将音频保存为文件
    """
    def __init__(self, output_file: str = OUTPUT_AUDIO_FILE):
        self.complete_event = threading.Event()
        self._output_file = output_file
        self._audio_data = bytearray()  # 用于收集所有音频数据
        self._start_time = None  # 开始发送文本的时间
        self._first_audio_time = None  # 收到首个音频的时间

    def set_start_time(self):
        """记录开始时间"""
        self._start_time = time.time()

    def on_open(self) -> None:
        print('[TTS] 连接已建立')

    def on_close(self, close_status_code, close_msg) -> None:
        print(f'[TTS] 连接关闭 code={close_status_code}, msg={close_msg}')

    def _save_to_wav(self) -> None:
        """将收集的 PCM 数据保存为 WAV 文件"""
        if not self._audio_data:
            print('[Warning] 没有音频数据可保存')
            return
        
        with wave.open(self._output_file, 'wb') as wf:
            wf.setnchannels(1)  # 单声道
            wf.setsampwidth(2)  # 16-bit = 2 bytes
            wf.setframerate(24000)  # 24000Hz
            wf.writeframes(bytes(self._audio_data))
        
        print(f'[TTS] 音频已保存到: {self._output_file}')

    def get_first_audio_delay(self) -> float:
        """获取首包延迟（毫秒）"""
        if self._start_time and self._first_audio_time:
            return (self._first_audio_time - self._start_time) * 1000
        return 0

    def on_event(self, response: dict) -> None:
        try:
            event_type = response.get('type', '')
            if event_type == 'session.created':
                print(f'[TTS] 会话开始: {response["session"]["id"]}')
            elif event_type == 'response.audio.delta':
                if self._first_audio_time is None:
                    self._first_audio_time = time.time()
                    print(f'[TTS] 首包延迟: {self.get_first_audio_delay():.0f}ms')
                audio_data = base64.b64decode(response['delta'])
                self._audio_data.extend(audio_data)  # 收集音频数据
            elif event_type == 'response.done':
                print(f'[TTS] 响应完成, Response ID: {qwen_tts_realtime.get_last_response_id()}')
            elif event_type == 'session.finished':
                print('[TTS] 会话结束')
                self._save_to_wav()  # 会话结束时保存音频
                self.complete_event.set()
        except Exception as e:
            print(f'[Error] 处理回调事件异常: {e}')

    def wait_for_finished(self):
        self.complete_event.wait()

# ======= 主执行逻辑 =======
if __name__ == '__main__':
    import sys
    
    # 创建音色模式：python tts.py --create-voice
    if len(sys.argv) > 1 and sys.argv[1] == '--create-voice':
        print('[系统] 创建音色...')
        voice_id = create_voice(VOICE_FILE_PATH, text=VOICE_SUBTITLE)
        print(f'[成功] 音色 ID: {voice_id}')
        print(f'请将此 ID 填入 tts.py 的 VOICE_ID 常量中')
        sys.exit(0)
    
    # 检查音色 ID
    if not VOICE_ID:
        print('[错误] 请先运行 `python tts.py --create-voice` 创建音色，并将返回的 ID 填入 VOICE_ID')
        sys.exit(1)
    
    init_dashscope_api_key()
    print('[系统] 初始化 Qwen TTS Realtime ...')

    callback = MyCallback()
    qwen_tts_realtime = QwenTtsRealtime(
        model=DEFAULT_TARGET_MODEL,
        callback=callback,
        # 以下为北京地域url，若使用新加坡地域的模型，需将url替换为：wss://dashscope-intl.aliyuncs.com/api-ws/v1/realtime
        url='wss://dashscope-intl.aliyuncs.com/api-ws/v1/realtime'
    )
    qwen_tts_realtime.connect()
    
    qwen_tts_realtime.update_session(
        voice=VOICE_ID,  # 使用预创建的音色 ID
        response_format=AudioFormat.PCM_24000HZ_MONO_16BIT,
        mode='server_commit'
    )

    callback.set_start_time()  # 记录开始时间
    for text_chunk in TEXT_TO_SYNTHESIZE:
        print(f'[发送文本]: {text_chunk}')
        qwen_tts_realtime.append_text(text_chunk)
        time.sleep(0.1)

    qwen_tts_realtime.finish()
    callback.wait_for_finished()

    print(f'[Metric] session_id={qwen_tts_realtime.get_session_id()}'
          f'first_audio_delay={callback.get_first_audio_delay():.0f}ms')