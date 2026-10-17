# 멀티모달 임베딩

## 지원 모델 (카탈로그 기준)

| 모델 | 모달리티 | 비고 |
|---|---|---|
| google/embeddinggemma-2 | 텍스트·이미지·오디오·비디오 | 768d, MRL 512/256/128. 텍스트 270M + 비전 170M + 오디오 300M |
| Qwen/Qwen3-VL-Embedding-2B / 8B | 텍스트·이미지·비디오 | 2B는 CPU에서도 사용 가능, 8B는 GPU 권장 |
| jinaai/jina-embeddings-v5-omni-small | 텍스트·이미지 | CC-BY-NC-4.0 (비상업) |
| sentence-transformers/clip-ViT-B-32, clip-ViT-L-14 | 텍스트·이미지 | 고전 베이스라인. 텍스트 77토큰, 영어 위주 |

UI의 **멀티모달** 화면은 modalities에 `text` 외 항목이 있는 모델만 보여 줍니다. 다른 모델을 쓰려면 모델 상세 화면에서 모달리티에 `image`를 추가하세요.

## EmbeddingGemma 2 프로필

| 프로필 | 로드 kwargs | 로드되는 파라미터 |
|---|---|---|
| text (기본) | `{"config_kwargs": {"vision_config": null, "audio_config": null}}` | ~270M |
| multimodal | `{"config_kwargs": {"audio_config": null}}` | ~440M (텍스트+비전) |

오디오까지 쓰려면 모델 상세 화면에서 "로드 kwargs - 멀티모달"을 `{}`로 바꾸면 전체(~740M)를 로드합니다. 같은 체크포인트이므로 텍스트로 만든 임베딩과 이미지 임베딩을 바로 비교할 수 있습니다.

입력 형식: EmbeddingGemma 2는 `{"image": PIL.Image}` 딕셔너리, CLIP은 PIL 이미지를 그대로 받습니다. 앱이 두 형식을 차례로 시도합니다.

## 실측 (CPU, Ryzen 16스레드, fp32)

생성한 테스트 이미지 5장(노을 바다, 빨간 원, 풀밭, 달 뜬 밤하늘, 파란 사각형)으로 측정한 결과입니다.

| 쿼리 | CLIP ViT-B/32 1위 | EmbeddingGemma 2 1위 |
|---|---|---|
| a sunset over the sea | sunset_sea (0.29) | sunset_sea (0.70) |
| 빨간 동그라미 | red_circle (0.22, 2위와 차이 0.01) | red_circle (0.73) |
| night sky with the moon | night_sky_moon (0.30) | night_sky_moon (0.75) |

- CLIP은 한국어 쿼리에서 1·2위 점수 차이가 거의 없어 신뢰도가 낮고, EmbeddingGemma 2는 한국어 쿼리도 뚜렷하게 구분했습니다.
- 속도: CLIP은 이미지 5장 + 쿼리에 약 0.2초, EmbeddingGemma 2는 CPU에서 약 20초(이미지당 약 4초)입니다. 이미지가 많으면 GPU를 쓰세요.

## 오디오 / 비디오

`sentence-transformers[audio,video]` extra는 이 환경(Python 3.14 + numpy 2.5)에서 의존성 해석이 실패해 기본 설치에서 뺐습니다(transformers[audio] → 구버전 numpy 요구). 필요하면 별도 환경에서 다음처럼 설치해 보세요.

```bash
uv pip install "sentence-transformers[audio,video]"
```

오디오는 16kHz 모노 입력을 권장합니다. 현재 UI는 텍스트→이미지 검색만 제공합니다. 오디오는 API 코드에서 `model.encode([{"audio": "file.wav"}])` 형태로 쓸 수 있습니다.
