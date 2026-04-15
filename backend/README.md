# AiTeachMe Backend

鏈洰褰曟槸 AITeachMe 鐨勫悗绔湇鍔★紝鍩轰簬 FastAPI + SQLModel锛岄潰鍚戔€滄湰鍦颁紭鍏堚€濈殑 AI 鍔╂暀鍦烘櫙銆?
## 褰撳墠鎺ュ彛褰㈡€?
- `GET /api/health`
- 涓氬姟鎺ュ彛浠?`POST` 涓轰富锛屽皯閲忕ǔ瀹氳鍙栨帴鍙ｄ娇鐢?`GET`
- JSON 鎺ュ彛缁熶竴杩斿洖锛?
```json
{
  "code": 0,
  "message": "ok",
  "data": {}
}
```

- `chat/send` 浠嶇劧淇濈暀鍘熺敓 SSE锛屼笉鍖?`ApiResponse`

## 涓昏璧勬簮

- `subjects`
- `files`
- `knowledge`
- `chat`
- `exam`
- `profile`

鏂板鐨勫姩浣滄帴鍙ｏ細

- `files/retry`
- `files/delete`
- `knowledge/retry`
- `knowledge/delete`
- `chat/clear`
- `exam/delete`

## 蹇€熷惎鍔?
### 1. 瀹夎渚濊禆

瑕佹眰锛歅ython `3.11+`

```bash
pip install -e .
```

### 2. 閰嶇疆 `.env`

鑷冲皯闇€瑕侊細

```env
LLM_API_KEY=sk-your-api-key-here
APP_MODE=local
AUTH_ENABLED=false
```

### 3. 鍚姩鏈嶅姟

```bash
uvicorn app.main:app --reload --port 8000
```

棣栨鍚姩鏃惰嫢缂哄皯 SQLite 鐩稿叧 Python 渚濊禆锛屾湇鍔′細鑷姩灏濊瘯瀹夎骞剁户缁惎鍔ㄣ€?鏁版嵁搴撴枃浠朵細鑷姩鍒涘缓鍦?`data/aiteachme.db`銆?濡傛灉妫€娴嬪埌 schema 杩囨湡锛屾湇鍔′細鑷姩澶囦唤鏃у簱骞堕噸寤烘柊搴撱€?
## LangGraph Dev 璋冭瘯

鍚庣鐜板湪棰濆鎻愪緵浜嗕竴缁勫彧鐢ㄤ簬璋冭瘯鐨?LangGraph 鍏ュ彛锛岄厤缃枃浠跺湪 `backend/langgraph.json`銆?
鍙皟璇曠殑 graph 鍖呮嫭锛?
- `ingest_fast_parse`
- `ingest_deep_enhance`
- `digest_kg`
- `digest_docgen`
- `digest_unified`
- `interact_chat`
- `examine_question_build`
- `examine_exam_grade`
- `profile_pipeline`

杩欎簺 graph 鐢?`langgraph.json` 鐩存帴鎸囧悜鍚勮嚜 workflow 妯″潡鍐呯殑鍥惧畾涔夋垨杞婚噺璋冭瘯宸ュ巶鍑芥暟锛屼笉鏇挎崲鍘熸湁 FastAPI / service 璋冪敤閾撅紝涔熶笉闇€瑕佸啀缁存姢涓€涓崟鐙殑姹囨€诲叆鍙ｆ枃浠躲€?
### 浣跨敤璇存槑

1. 浣跨敤 Python `3.11+`
2. 鍦?`backend/` 鐩綍杩愯锛?
```bash
pip install -e .
langgraph dev --config langgraph.json
```

### 璇存槑

- `backend` 鐜板湪灏?Python 鐗堟湰瑕佹眰鏀舵暃涓?`3.11+`锛岃繖鏍?`pip install -e .` 浼氫竴骞跺畨瑁?LangGraph Dev 鎵€闇€渚濊禆銆?- `interact_chat` 浣跨敤鐨勬槸鈥滈潪鐢熶骇 SSE 澶栧３鈥濈殑璋冭瘯鍥撅紝鐩殑鏄湪 Studio 閲岀洿鎺ヨ瀵熷畬鏁?state锛岃€屼笉鏀瑰彉绾夸笂鑱婂ぉ鎺ュ彛琛屼负銆?- `profile_pipeline` 鏄负璋冭瘯鏂板鐨勫彲鎵ц graph锛涘師鏈?`profile` 姒傝鍥句粛鐒朵繚鐣欍€?
### LangSmith

濡傛灉甯屾湜鍦?LangSmith 涓洿鎺ユ煡鐪?workflow 涓?LLM 璋冪敤閾捐矾锛屽彲棰濆閰嶇疆锛?
```env
LANGSMITH_TRACING=true
LANGSMITH_API_KEY=lsv2_xxx
LANGSMITH_PROJECT=AITeachMe
LANGSMITH_CAPTURE_INPUTS=true
LANGSMITH_CAPTURE_OUTPUTS=true
```

褰撳墠绾﹀畾涓嬶紝workflow 缁熶竴杩愯鍏ュ彛鍜屽叡浜?infra trace 杈圭晫浼氳嚜鍔ㄧ户鎵?tracing 涓婁笅鏂囷紝鍥犳涓嶉渶瑕佸湪姣忎釜涓氬姟鑺傜偣閲岄噸澶嶆墜鍐欒娴嬩唬鐮併€?`LANGSMITH_CAPTURE_INPUTS / LANGSMITH_CAPTURE_OUTPUTS` 鐜板湪涓嶄粎褰卞搷 LLM span锛屼篃浼氬奖鍝?retriever / reader / tool / runtime 鐨勮緭鍏ヨ緭鍑洪瑙堬紱鍦?`APP_MODE=local` 涓嬮粯璁ゅ紑鍚紝鏄惧紡閰嶇疆鍙敤浜庤鐩栭粯璁ょ瓥鐣ャ€?
## 鎵嬪姩楠岃瘉

鏌ョ湅浠ヤ笅鏂囨。锛?
- [docs/design.md](./docs/design.md)
- [docs/local-dev.md](./docs/local-dev.md)
- [docs/manual-testing.md](./docs/manual-testing.md)
- [docs/implementation-log.md](./docs/implementation-log.md)
- [playground/README.md](./playground/README.md)

