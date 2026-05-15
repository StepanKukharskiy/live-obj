# Grasshopper GHPython component: tiny Spellshape chat/source memory.
#
# Inputs to create:
#   live_obj       str   latest OBJ from LLM node
#   next_history   str   latest history from LLM node
#   save           bool  connect a Boolean Button; stores incoming values
#   reset          bool  clears stored memory
#
# Outputs to create:
#   current_obj
#   history
#   status
#
# Usage:
#   LLM.live_obj      -> memory.live_obj
#   LLM.next_history  -> memory.next_history
#   memory.current_obj -> LLM.current_obj
#   memory.history     -> LLM.history
#
# Press save after a successful LLM run. Press reset to start a new chat.

import scriptcontext as sc


def safe_str(value):
    return "" if value is None else str(value)


def memory_key(name):
    try:
        guid = str(ghenv.Component.InstanceGuid)
    except Exception:
        guid = "default"
    return "spellshape_chat_memory:%s:%s" % (guid, name)


obj_key = memory_key("current_obj")
history_key = memory_key("history")

if reset:
    sc.sticky[obj_key] = ""
    sc.sticky[history_key] = ""
    status = "reset"
elif save:
    incoming_obj = safe_str(live_obj).strip()
    incoming_history = safe_str(next_history).strip()
    if incoming_obj:
        sc.sticky[obj_key] = incoming_obj
    if incoming_history:
        sc.sticky[history_key] = incoming_history
    status = "saved: obj=%d chars history=%d chars" % (
        len(sc.sticky.get(obj_key, "") or ""),
        len(sc.sticky.get(history_key, "") or ""),
    )
else:
    status = "ready: obj=%d chars history=%d chars" % (
        len(sc.sticky.get(obj_key, "") or ""),
        len(sc.sticky.get(history_key, "") or ""),
    )

current_obj = sc.sticky.get(obj_key, "") or ""
history = sc.sticky.get(history_key, "") or ""

try:
    ghenv.Component.Message = status
except Exception:
    pass
