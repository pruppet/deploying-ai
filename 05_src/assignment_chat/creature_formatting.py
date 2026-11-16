# Render Open5e creature records as compact, table-ready Markdown stat blocks.
import math
from fractions import Fraction

ABILITIES = ["strength", "dexterity", "constitution",
             "intelligence", "wisdom", "charisma"]
ABBREVIATIONS = {a: a[:3].upper() for a in ABILITIES}

# Display order for action groups. Types not listed here are still shown,
# after these, using a title-cased version of the API's action_type value.
ACTION_SECTIONS = [
    ("ACTION", "Actions"),
    ("BONUS_ACTION", "Bonus Actions"),
    ("REACTION", "Reactions"),
    ("LEGENDARY_ACTION", "Legendary Actions"),
]


def _signed(value: int) -> str:
    return f"+{value}" if value >= 0 else str(value)


def _challenge_rating(cr) -> str:
    if cr is None:
        return "unknown"
    return str(Fraction(cr).limit_denominator(8))  # 0.25 -> "1/4", 14.0 -> "14"


def _proficiency_bonus(creature: dict):
    """Return (bonus, derived). The API may leave this null; if so, use the CR table."""
    bonus = creature.get("proficiency_bonus")
    if bonus is not None:
        return bonus, False
    cr = creature.get("challenge_rating")
    if cr is None:
        return None, False
    return 2 + max(0, math.ceil(cr) - 1) // 4, True


def _speed(creature: dict) -> str:
    speed = creature.get("speed") or {}
    parts = []
    if speed.get("walk"):
        parts.append(f"{speed['walk']} ft.")
    for mode in ("burrow", "climb", "fly", "swim"):
        if speed.get(mode):
            label = f"{mode} {speed[mode]} ft."
            if mode == "fly" and (creature.get("speed_all") or {}).get("hover"):
                label += " (hover)"
            parts.append(label)
    return ", ".join(parts) or "unknown"


def _senses(creature: dict) -> str:
    parts = []
    for field, label in (("blindsight_range", "Blindsight"),
                         ("darkvision_range", "Darkvision"),
                         ("tremorsense_range", "Tremorsense"),
                         ("truesight_range", "Truesight")):
        if creature.get(field):
            parts.append(f"{label} {creature[field]} ft.")
    if creature.get("passive_perception") is not None:
        parts.append(f"Passive Perception {creature['passive_perception']}")
    return ", ".join(parts)


def _usage_note(limits) -> str:
    if not limits:
        return ""
    kind, param = limits.get("type"), limits.get("param")
    if kind == "RECHARGE_ON_ROLL" and param is not None:
        return f" (Recharge {param}–6)" if param < 6 else " (Recharge 6)"
    # Other limit types are shown as provided rather than interpreted.
    label = str(kind).replace("_", " ").lower()
    return f" ({label} {param})" if param is not None else f" ({label})"


def _indent_desc(desc: str) -> str:
    """Keep multi-line descriptions (e.g. spell lists) nested under their bullet."""
    lines = [line for line in (desc or "").strip().splitlines() if line.strip()]
    return "\n".join([lines[0]] + ["  " + line for line in lines[1:]]) if lines else ""


def _defences(creature: dict) -> list:
    data = creature.get("resistances_and_immunities") or {}
    lines = []
    for field, label in (("damage_vulnerabilities_display", "Vulnerabilities"),
                         ("damage_resistances_display", "Resistances"),
                         ("damage_immunities_display", "Damage Immunities"),
                         ("condition_immunities_display", "Condition Immunities")):
        if data.get(field):
            lines.append(f"**{label}:** {data[field].capitalize()}")
    return lines


def _action_sections(actions: list) -> list:
    lines = []
    known = [code for code, _ in ACTION_SECTIONS]
    extra = sorted({a.get("action_type") for a in actions} - set(known) - {None})
    sections = ACTION_SECTIONS + [(code, code.replace("_", " ").title()) for code in extra]

    for code, heading in sections:
        group = sorted((a for a in actions if a.get("action_type") == code),
                       key=lambda a: a.get("order_in_statblock") or 0)
        if not group:
            continue
        lines.append(f"\n**{heading}**")
        if code == "LEGENDARY_ACTION":
            lines.append("_Uses per round are not included in the API data; "
                         "check the source stat block._")
        for action in group:
            name = action.get("name", "Unnamed")
            if code == "LEGENDARY_ACTION" and (action.get("legendary_action_cost") or 1) > 1:
                name += f" (Costs {action['legendary_action_cost']} Actions)"
            name += _usage_note(action.get("usage_limits"))
            lines.append(f"- **{name}.** {_indent_desc(action.get('desc', ''))}")
    return lines


def format_creature(data: dict) -> str:
    # Unwrap a full API response.
    if "results" in data:
        results = data.get("results") or []
        if not results:
            return "No creature was found."
        if len(results) > 1:
            names = ", ".join(r.get("name", "Unnamed") for r in results)
            return f"Several creatures matched: {names}. Please choose one."
        data = results[0]

    c = data
    size = (c.get("size") or {}).get("name", "")
    ctype = (c.get("type") or {}).get("name", "")
    pb, derived = _proficiency_bonus(c)
    xp = c.get("experience_points")

    header = f"{size} {ctype}".strip()
    if c.get("alignment"):
        header += f", {c['alignment']}"
    rating = f"CR {_challenge_rating(c.get('challenge_rating'))}"
    if xp is not None:
        rating += f" ({xp:,} XP)"
    if pb is not None:
        rating += f", Proficiency Bonus {_signed(pb)}" + (" (from CR)" if derived else "")

    lines = [f"### {c.get('name', 'Unknown creature')}", f"_{header}_  ", rating, ""]

    # Core combat numbers
    ac = f"**Armour Class:** {c.get('armor_class', '?')}"
    if c.get("armor_detail"):
        ac += f" ({c['armor_detail']})"
    lines.append(ac + "  ")
    hp = f"**Hit Points:** {c.get('hit_points', '?')}"
    if c.get("hit_dice"):
        hp += f" ({c['hit_dice']})"
    lines.append(hp + "  ")
    if c.get("initiative_bonus") is not None:
        bonus = c["initiative_bonus"]
        lines.append(f"**Initiative:** {_signed(bonus)} ({10 + bonus})  ")
    lines.append(f"**Speed:** {_speed(c)}")
    lines.append("")

    # Ability scores
    scores = c.get("ability_scores") or {}
    mods = c.get("modifiers") or {}
    if scores:
        lines.append("| " + " | ".join(ABBREVIATIONS[a] for a in ABILITIES) + " |")
        lines.append("|" + "---|" * len(ABILITIES))
        lines.append("| " + " | ".join(
            f"{scores.get(a, '?')} ({_signed(mods[a])})" if a in mods else str(scores.get(a, "?"))
            for a in ABILITIES) + " |")
        lines.append("")

    saves = c.get("saving_throws") or {}
    if saves:
        lines.append("**Saving Throws:** " + ", ".join(
            f"{ABBREVIATIONS[a]} {_signed(saves[a])}" for a in ABILITIES if a in saves) + "  ")
    skills = c.get("skill_bonuses") or {}
    if skills:
        lines.append("**Skills:** " + ", ".join(
            f"{k.replace('_', ' ').title()} {_signed(v)}" for k, v in skills.items()) + "  ")
    lines.extend(line + "  " for line in _defences(c))
    if _senses(c):
        lines.append(f"**Senses:** {_senses(c)}  ")
    languages = (c.get("languages") or {}).get("as_string")
    if languages:
        lines.append(f"**Languages:** {languages}")

    traits = c.get("traits") or []
    if traits:
        lines.append("\n**Traits**")
        for t in traits:
            lines.append(f"- **{t.get('name', 'Unnamed')}.** {_indent_desc(t.get('desc', ''))}")

    lines.extend(_action_sections(c.get("actions") or []))
    return "\n".join(lines)