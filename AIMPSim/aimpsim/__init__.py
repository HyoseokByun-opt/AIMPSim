"""AIMPSim - requests in words for MPSim.

A request such as "에폭시에 구형 알루미나 55 vol%, 열전도도 구해줘" or "epoxy
with 60 vol% silica, thermal conductivity and CTE" is read into an MPSim
case - a run, a DOE study, a calibration or an optimisation - summarised,
and run when the user agrees. A small local language model shipped with
AIMPSim (offline, llama.cpp) reads the request, however it is written; rules
check what it read against the sentence (reader.py) and read alone when
there is no model.

AIMPSim is used with the latest MPSim: MPSim finds it beside itself and
shows it as the AI tab (between Home and Material).
"""
from __future__ import annotations

__version__ = "0.2.0"
MPSIM_MIN = "5.6.3"


def register(app, host):
    """Called by MPSim's server: `host` gives the material library
    ('library'), a validation ('validate': form -> error text or None), the
    plan of a case ('plan': form -> plan dict), the machine's cores
    ('cores') and MPSim's version ('version')."""
    from .web import Assistant, blueprint
    assistant = Assistant(host)
    app.register_blueprint(blueprint(assistant))
    app.config["AIMPSIM"] = {"version": __version__, "js": "/ai/static/aimpsim.js", "css": "/ai/static/aimpsim.css"}
    return assistant


def _version_tuple(v):
    out = []
    for p in str(v).split("."):
        try:
            out.append(int(p))
        except ValueError:
            out.append(0)
    return tuple(out)


def compatible(mpsim_version):
    return _version_tuple(mpsim_version) >= _version_tuple(MPSIM_MIN)
