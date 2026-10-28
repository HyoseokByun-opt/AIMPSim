"""Start a local model and read a few requests with it, printing the raw
answer, the checked intent and the time.

    python tests/llm_smoke.py <llama-server.exe> <model.gguf> [threads] [sentence ...]
"""
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)
from run_tests import find_mpsim, host_for  # noqa: E402
from aimpsim.lexicon import Lexicon  # noqa: E402
from aimpsim.llm import LocalLLM  # noqa: E402
from aimpsim.parser import parse  # noqa: E402
from aimpsim import reader  # noqa: E402

exe, model = sys.argv[1], sys.argv[2]
threads = int(sys.argv[3]) if len(sys.argv) > 3 else 6
texts = sys.argv[4:] or ["에폭시에 알루미나 반 정도 섞으면 열이 얼마나 잘 빠질까?",
                         "에폭시랑 알루미나 비율을 4대6으로 해서 열전도도",
                         "Not alumina - use boron nitride, 30% in epoxy, for heat spreading"]
host = host_for(find_mpsim())
lex = Lexicon(host.get("library") or [])
llm = LocalLLM({"server_exe": exe, "model": model, "threads": threads,
                "log": os.path.join(os.environ.get("TEMP", "."), "llama_smoke.log")})
t0 = time.time()
ok = llm._ping() or llm._start()
print("server", ok, f"{time.time() - t0:.1f} s")
try:
    for text in texts:
        js = llm.chat_json(reader.messages(lex, text), reader.SCHEMA)
        tm = llm.last.get("timings") or {}
        print(f"\n{text}\n  {llm.last.get('seconds')} s  prompt {tm.get('prompt_n')} tok @ {tm.get('prompt_per_second', 0):.0f}/s,"
              f" gen {tm.get('predicted_n')} tok @ {tm.get('predicted_per_second', 0):.1f}/s")
        print("  raw:", json.dumps(js, ensure_ascii=False))
        it, rep = reader.build_intent(js, text, lex, parse(text, lex))
        print("  ->", (it.get("matrix") or {}).get("id"),
              [(f.get("id"), (f.get("content") or {}).get("value")) for f in it["fillers"]], it["analyses"], it.get("task"))
        print("  report:", rep)
finally:
    llm.close()
