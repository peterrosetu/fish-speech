﻿import os

os.environ["MODELSCOPE_CACHE"] = ".cache/"

import string
import time
from threading import Lock

import librosa
import numpy as np
import opencc
import torch
from faster_whisper import WhisperModel

t2s_converter = opencc.OpenCC("t2s")


def load_model(*, device="cuda"):
    model = WhisperModel(
        "medium",
        device=device,
        compute_type="float16",
        download_root="faster_whisper",
    )
    print("faster_whisper loaded!")
    return model


@torch.no_grad()
def batch_asr_internal(model: WhisperModel, audios, sr):
    resampled_audios = []
    for audio in audios:

        if isinstance(audio, np.ndarray):
            audio = torch.from_numpy(audio).float()

        if audio.dim() > 1:
            audio = audio.squeeze()

        assert audio.dim() == 1
        audio_np = audio.numpy()
        resampled_audio = librosa.resample(audio_np, orig_sr=sr, target_sr=16000)
        resampled_audios.append(torch.from_numpy(resampled_audio))

    trans_results = []

    for resampled_audio in resampled_audios:
        segments, info = model.transcribe(
            resampled_audio.numpy(), language=None, beam_size=5
        )
        trans_results.append(list(segments))

    results = []
    for trans_res, audio in zip(trans_results, audios):

        duration = len(audio) / sr * 1000
        huge_gap = False
        max_gap = 0.0

        text = None
        last_tr = None

        for tr in trans_res:
            delta = tr.text.strip()
            if tr.id > 1:
                max_gap = max(tr.start - last_tr.end, max_gap)
                text += delta
            else:
                text = delta

            last_tr = tr
            if max_gap > 3.0:
                huge_gap = True

        sim_text = t2s_converter.convert(text)
        results.append(
            {
                "text": sim_text,
                "duration": duration,
                "huge_gap": huge_gap,
            }
        )

    return results


global_lock = Lock()


def batch_asr(model, audios, sr):
    return batch_asr_internal(model, audios, sr)


def is_chinese(text):
    return True


def calculate_wer(text1, text2):
    # 将文本分割成字符列表
    chars1 = remove_punctuation(text1)
    chars2 = remove_punctuation(text2)

    # 计算编辑距离
    m, n = len(chars1), len(chars2)
    dp = [[0] * (n + 1) for _ in range(m + 1)]

    for i in range(m + 1):
        dp[i][0] = i
    for j in range(n + 1):
        dp[0][j] = j

    for i in range(1, m + 1):
        for j in range(1, n + 1):
            if chars1[i - 1] == chars2[j - 1]:
                dp[i][j] = dp[i - 1][j - 1]
            else:
                dp[i][j] = min(dp[i - 1][j], dp[i][j - 1], dp[i - 1][j - 1]) + 1

    # WER
    edits = dp[m][n]
    tot = max(len(chars1), len(chars2))
    wer = edits / tot
    print("            gt:   ", chars1)
    print("          pred:   ", chars2)
    print(" edits/tot = wer: ", edits, "/", tot, "=", wer)
    return wer


def remove_punctuation(text):
    chinese_punctuation = (
        " \n\t”“！？｡。＂＃＄％＆＇（）＊＋，－／：；＜＝＞＠［＼］＾＿｀｛｜｝～｟｠｢｣､、〃《》「」『』【】〔〕〖〗〘〙〚〛〜〝〞〟〰〾〿–—"
        '‛""„‟…‧﹏'
    )
    all_punctuation = string.punctuation + chinese_punctuation
    translator = str.maketrans("", "", all_punctuation)
    text_without_punctuation = text.translate(translator)
    return text_without_punctuation


if __name__ == "__main__":
    model = load_model()
    audios = [
        librosa.load("44100.wav", sr=44100)[0],
        librosa.load("lengyue.wav", sr=44100)[0],
    ]
    print(np.array(audios[0]))
    print(batch_asr(model, audios, 44100))

    start_time = time.time()
    for _ in range(10):
        print(batch_asr(model, audios, 44100))
    print("Time taken:", time.time() - start_time)
