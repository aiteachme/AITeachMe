# Digest 妯″潡璇存槑

鏈€鍚庢洿鏂帮細2026-04-16

`digest/` 璐熻矗鎶婅祫鏂欎粠鈥滃彲妫€绱㈠唴瀹光€濊繘涓€姝ョ紪鎺掓垚 confirmed plan銆佺煡璇嗘枃妗ｅ拰鐭ヨ瘑鍥捐氨銆傚畠涔熸槸鏈疆 workflows 鍗曞眰鍖栭噸鏋勭殑绗竴钀藉湴鍖哄煙銆?
## 褰撳墠 canonical 缁撴瀯

```text
digest/
  __init__.py
  README.md
  application/
  planner/
  docgen/
  knowledge_graph/
  unified/
  shared/
```

璇存槑锛?
- `planner/` 璐熻矗鐢熸垚 confirmed plan
- `docgen/` 璐熻矗鎸?confirmed plan 鐢熸垚鐭ヨ瘑鏂囨。
- `knowledge_graph/` 璐熻矗鐭ヨ瘑鍥捐氨閾捐矾
- `unified/` 璐熻矗缂栨帓鍏变韩鍑嗗銆乨ocgen銆乲nowledge graph 绛夌粍鍚堟祦绋?- `application/` 鏄?Digest 妯″潡绾?API-facing 鐢ㄤ緥钀界偣
- `shared/` 鏄法閾捐矾鍏辩敤鐨?contracts / models / prepare / material_profile / metrics 瀹炵幇灞?- `_shared/` 鍙繚鐣欑湡瀹?Digest 鏁欏璇箟锛屼緥濡?runtime_config 涓?pedagogy锛涗笉瑕佹柊澧炵┖杞彂闂ㄩ潰
- 鍚勯摼璺嚜宸辩殑鏋勫缓鎽樿鏀惧湪瀵瑰簲閾捐矾 `lib/reporting.py`锛屼笉瑕佸啀鏂板椤跺眰 observability 浼摼璺?
## 瀵瑰鍏ュ彛

涓婂眰浼樺厛浣跨敤锛?
```python
from app.workflows.digest import run_docgen_workflow, run_graph_digest_workflow
from app.workflows.digest.planner import run_build_planner_workflow
```

## 杩佺Щ绾﹀畾

- 妯″潡鏍瑰彧鍋氳仛鍚?- 妯″潡绾?API-facing 鐢ㄤ緥杩涘叆 `application/`
- 鏂?prompt 鏀惧悇鑷摼璺?`prompts/`
- 鏂?helper 鏀惧悇鑷摼璺?`lib/`
- 璺ㄩ摼璺叡浜兘鍔涜蛋 `shared/`锛涗笉瑕佸啀鏂板鍙仛杞彂鐨?`_shared/` 绌洪棬闈?- Digest 鏂囨。鏁欏璇箟璧?`_shared/runtime_config.py` 涓?`_shared/pedagogy/`
- 鏃фā鍧楃骇鍏煎鏂囦欢鏆傛椂淇濈暀锛屼絾鏂颁唬鐮佷紭鍏堣蛋鍚勯摼璺洰褰?