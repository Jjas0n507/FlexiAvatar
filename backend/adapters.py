"""
适配器工厂 — 根据 config 的 engine 字段动态创建适配器实例。

用法:
    from backend.adapters import create_vad, create_asr, create_llm, create_tts
    from backend.config import config

    vad = create_vad(config)
    asr = create_asr(config)
    llm = create_llm(config)
    tts = create_tts(config)
"""

from backend.config import Config


def create_vad(config: Config):
    """创建 VAD 适配器实例"""
    engine = config.get("vad.engine", "silero")
    if engine == "silero":
        from backend.vad.silero_adapter import SileroVAD
        return SileroVAD(threshold=config.get("vad.speech_threshold", 0.5))
    raise ValueError(f"Unknown VAD engine: {engine}")


def create_asr(config: Config):
    """创建 ASR 适配器实例"""
    engine = config.get("asr.engine", "whisper")
    if engine == "whisper":
        from backend.asr.whisper_adapter import WhisperASR
        return WhisperASR(
            model_size=config.get("asr.whisper.model_size", "base"),
            language="zh",
            device=config.get("asr.whisper.device", "cpu"),
            compute_type=config.get("asr.whisper.compute_type", "int8"),
            beam_size=config.get("asr.whisper.beam_size", 5),
        )
    elif engine == "funasr":
        from backend.asr.funasr_adapter import FunASRAdapter
        return FunASRAdapter(
            model=config.get("asr.funasr.model", "iic/SenseVoiceSmall"),
            device=config.get("asr.funasr.device", "cpu"),
        )
    raise ValueError(f"Unknown ASR engine: {engine}")


def create_llm(config: Config):
    """创建 LLM 适配器实例"""
    engine = config.get("llm.engine", "openai")
    if engine == "openai":
        from backend.llm.openai_adapter import OpenAIAdapter
        return OpenAIAdapter()
    elif engine == "ollama":
        from backend.llm.ollama_adapter import OllamaAdapter
        return OllamaAdapter()
    raise ValueError(f"Unknown LLM engine: {engine}")


def create_tts(config: Config):
    """创建 TTS 适配器实例"""
    engine = config.get("tts.engine", "edge-tts")
    if engine == "edge-tts":
        from backend.tts.edge_tts_adapter import EdgeTTSAdapter
        return EdgeTTSAdapter(
            voice=config.get("tts.edge_tts.voice", "zh-CN-XiaoxiaoNeural"),
            speed=config.get("tts.edge_tts.speed", "+10%"),
        )
    raise ValueError(f"Unknown TTS engine: {engine}")
