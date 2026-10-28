"""How fast the local model reads requests on this PC: the first request
(the instructions read once) and the next ones, for a llama-server build,
a model and a number of threads.

    python tests/llm_speed.py <llama-server.exe> <model.gguf> [--threads 6] [--args "-ngl 99"]
"""
import argparse
import os
import statistics
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)
from run_tests import find_mpsim, host_for  # noqa: E402
from aimpsim import reader  # noqa: E402
from aimpsim.lexicon import Lexicon  # noqa: E402
from aimpsim.llm import LocalLLM  # noqa: E402

TEXTS = ["에폭시에 알루미나 반 정도 섞으면 열이 얼마나 잘 빠질까?",
         "epoxy with alumina, 55%, actually make that 60%, thermal conductivity",
         "실리콘에 AlN 50% 넣고 thermal conductivity 정확하게",
         "에폭시에 알루미나를 40에서 60까지 바꿔가며 열전도도 어떻게 변하나 보고싶어",
         "k가 25 W/mK인 알루미나를 에폭시에 50% 넣었을 때 열전도도",
         "BN 판상인데 지름 20마이크로 두께 1마이크로, 실리콘에 30% 열전도",
         "Not alumina - use boron nitride, 30% in epoxy, for heat spreading",
         "에폭시 실리카 30%일때 0.45, 50%일때 0.8 W/mK 측정값으로 보정"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("exe")
    ap.add_argument("model")
    ap.add_argument("--threads", type=int, default=6)
    ap.add_argument("--args", default="")
    a = ap.parse_args()
    lex = Lexicon(host_for(find_mpsim()).get("library") or [])
    llm = LocalLLM({"server_exe": a.exe, "model": a.model, "threads": a.threads,
                    "args": a.args.split() if a.args else [], "timeout_s": 300})
    t0 = time.time()
    if not llm._start():
        sys.exit("the server did not start")
    start = time.time() - t0
    secs, gen, pp = [], [], []
    try:
        for i, text in enumerate(TEXTS):
            t = time.time()
            llm.chat_json(reader.messages(lex, text), reader.SCHEMA)
            secs.append(time.time() - t)
            tm = (llm.last or {}).get("timings") or {}
            if tm:
                gen.append(tm.get("predicted_per_second") or 0)
                pp.append(tm.get("prompt_per_second") or 0)
    finally:
        llm.close()
    print(f"{os.path.basename(a.model)}  threads {a.threads}  {a.args or '(cpu)'}")
    print(f"  server start {start:.1f} s, first request {secs[0]:.1f} s (instructions {pp[0]:.0f} tok/s), "
          f"then median {statistics.median(secs[1:]):.1f} s, max {max(secs[1:]):.1f} s, "
          f"generation {statistics.median(gen[1:]):.1f} tok/s")


if __name__ == "__main__":
    main()
