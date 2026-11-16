# Provide bounded dice rolls and XP-budget encounter calculations as chat tools.
import random
import re
from fractions import Fraction
from typing import Any

from langchain.tools import tool
from pydantic import BaseModel, Field


_rng = random.SystemRandom()

MAX_DICE = 100
MAX_SIDES = 1000

_DICE_TERM = re.compile(r"^([+-]?)(\d*)d(\d+)(?:(kh|kl|dh|dl)(\d+))?$")
_CONSTANT_TERM = re.compile(r"^([+-]?)(\d+)$")

_PHRASES = [
    (r"drop(?:ping)?\s*(?:the\s*)?lowest", "dl1"),
    (r"drop(?:ping)?\s*(?:the\s*)?highest", "dh1"),
    (r"keep(?:ing)?\s*(?:the\s*)?highest", "kh1"),
    (r"keep(?:ing)?\s*(?:the\s*)?lowest", "kl1"),
    (r"d20\s*(?:with\s*)?advantage", "2d20kh1"),
    (r"d20\s*(?:with\s*)?disadvantage", "2d20kl1"),
]

XP_BUDGET_PER_CHARACTER = {
    1: (50, 75, 100),         2: (100, 150, 200),       3: (150, 225, 400),
    4: (250, 375, 500),       5: (500, 750, 1100),      6: (600, 1000, 1400),
    7: (750, 1300, 1700),     8: (1000, 1700, 2100),    9: (1300, 2000, 2600),
    10: (1600, 2300, 3100),   11: (1900, 2900, 4100),  12: (2200, 3700, 4700),
    13: (2600, 4200, 5400),   14: (2900, 4900, 6200),  15: (3300, 5400, 7800),
    16: (3800, 6100, 9800),   17: (4500, 7200, 11700), 18: (5000, 8700, 14200),
    19: (5500, 10700, 17200), 20: (6400, 13200, 22000),
}

XP_BY_CR = {
    "0": 10, "1/8": 25, "1/4": 50, "1/2": 100, "1": 200, "2": 450, "3": 700,
    "4": 1100, "5": 1800, "6": 2300, "7": 2900, "8": 3900, "9": 5000,
    "10": 5900, "11": 7200, "12": 8400, "13": 10000, "14": 11500, "15": 13000,
    "16": 15000, "17": 18000, "18": 20000, "19": 22000, "20": 25000,
    "21": 33000, "22": 41000, "23": 50000, "24": 62000, "25": 75000,
    "26": 90000, "27": 105000, "28": 120000, "29": 135000, "30": 155000,
}


class EncounterMonsterInput(BaseModel):
    name: str = Field(description="Creature name.")
    count: int = Field(ge=1, description="Number of creatures.")
    xp: int | None = Field(
        default=None,
        ge=0,
        description="XP per creature, preferably looked up from the D&D API.",
    )
    cr: str | None = Field(
        default=None,
        description="Challenge rating, required when XP is unavailable.",
    )


class EncounterInput(BaseModel):
    party_levels: list[int] = Field(
        min_length=1,
        description="One character level per party member, from 1 to 20.",
    )
    monsters: list[EncounterMonsterInput] = Field(
        min_length=1,
        description="Creatures in the encounter, with XP or challenge rating.",
    )


def _normalise(expression: str) -> str:
    if not isinstance(expression, str):
        raise ValueError("The dice expression must be text.")

    text = expression.lower().strip()
    text = re.sub(r"\band\b", "+", text)
    text = re.sub(r"\b(roll|the|a|an)\b", " ", text)
    for pattern, replacement in _PHRASES:
        text = re.sub(pattern, replacement, text)
    return re.sub(r"\s+", "", text)


def roll_dice_result(expression: str, rng: Any = None) -> dict[str, Any]:
    """Roll standard dice notation, including keep/drop and advantage notation."""
    rng = rng or _rng
    text = _normalise(expression)
    if not text:
        raise ValueError("No dice expression was given.")

    terms = re.findall(r"[+-]?[^+-]+", text)
    if not terms or "".join(terms) != text:
        raise ValueError(f"Could not read the dice expression {expression!r}.")

    total = 0
    breakdown = []
    for term in terms:
        constant = _CONSTANT_TERM.match(term)
        if constant:
            sign = -1 if constant.group(1) == "-" else 1
            value = sign * int(constant.group(2))
            total += value
            breakdown.append({"term": term, "subtotal": value})
            continue

        dice = _DICE_TERM.match(term)
        if not dice:
            raise ValueError(f"Could not read {term!r} in {expression!r}.")

        sign_text, count_text, sides_text, mode, mode_n = dice.groups()
        sign = -1 if sign_text == "-" else 1
        count = int(count_text) if count_text else 1
        sides = int(sides_text)

        if not 1 <= count <= MAX_DICE:
            raise ValueError(f"Number of dice must be between 1 and {MAX_DICE}.")
        if not 2 <= sides <= MAX_SIDES:
            raise ValueError(f"Dice must have between 2 and {MAX_SIDES} sides.")

        rolls = [rng.randint(1, sides) for _ in range(count)]
        kept = list(rolls)
        if mode:
            keep_or_drop_count = int(mode_n)
            if not 1 <= keep_or_drop_count <= count or (
                mode in ("dh", "dl") and keep_or_drop_count >= count
            ):
                raise ValueError(f"Cannot apply {mode}{keep_or_drop_count} to {count} dice.")
            ordered = sorted(rolls)
            if mode == "kh":
                kept = ordered[-keep_or_drop_count:]
            elif mode == "kl":
                kept = ordered[:keep_or_drop_count]
            elif mode == "dl":
                kept = ordered[keep_or_drop_count:]
            elif mode == "dh":
                kept = ordered[:-keep_or_drop_count]

        subtotal = sign * sum(kept)
        total += subtotal
        breakdown.append({
            "term": term,
            "rolls": rolls,
            "kept": sorted(kept, reverse=True),
            "subtotal": subtotal,
        })

    return {
        "expression": expression,
        "notation": text,
        "total": total,
        "breakdown": breakdown,
    }


@tool
def roll_dice(expression: str) -> dict[str, Any]:
    """Roll dice such as d20, 2d6+3, 4d6 drop lowest, or d20 with advantage.

    Include each individual die roll and the total in the result.
    """
    return roll_dice_result(expression)


def _cr_key(cr: Any) -> str:
    try:
        return str(Fraction(str(cr)))
    except (TypeError, ValueError, ZeroDivisionError) as exc:
        raise ValueError(f"{cr!r} is not a valid challenge rating.") from exc


def _cr_value(cr: Any) -> float:
    return float(Fraction(_cr_key(cr)))


def _require_integer(value: Any, label: str, minimum: int) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{label} must be an integer of at least {minimum}.")
    try:
        integer = int(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{label} must be an integer of at least {minimum}.") from exc
    if str(integer) != str(value).strip() and not isinstance(value, int):
        raise ValueError(f"{label} must be an integer of at least {minimum}.")
    if integer < minimum:
        raise ValueError(f"{label} must be at least {minimum}.")
    return integer


def calculate_encounter_result(
    party_levels: list[int],
    monsters: list[dict[str, Any]],
) -> dict[str, Any]:
    """Calculate encounter difficulty from party levels and monster XP or CR."""
    if not isinstance(party_levels, list) or not party_levels:
        raise ValueError("At least one party member's level is required.")
    if not isinstance(monsters, list) or not monsters:
        raise ValueError("At least one creature is required.")

    levels = []
    for level in party_levels:
        level = _require_integer(level, "Character level", 1)
        if level not in XP_BUDGET_PER_CHARACTER:
            raise ValueError(f"Character level must be between 1 and 20, not {level}.")
        levels.append(level)

    budgets = {"Low": 0, "Moderate": 0, "High": 0}
    for level in levels:
        low, moderate, high = XP_BUDGET_PER_CHARACTER[level]
        budgets["Low"] += low
        budgets["Moderate"] += moderate
        budgets["High"] += high

    total_xp, creature_count, lines, notes = 0, 0, [], []
    highest_level = max(levels)

    for monster in monsters:
        if isinstance(monster, BaseModel):
            monster = monster.model_dump()
        if not isinstance(monster, dict):
            raise ValueError("Each creature must be provided as an object.")
        name = monster.get("name", "Unnamed creature")
        if not isinstance(name, str) or not name.strip():
            raise ValueError("Each creature must have a non-empty name.")
        count = _require_integer(monster.get("count", 1), f"Count for {name}", 1)

        if monster.get("xp") is not None:
            xp = _require_integer(monster["xp"], f"XP for {name}", 0)
        elif monster.get("cr") is not None:
            cr_key = _cr_key(monster["cr"])
            xp = XP_BY_CR.get(cr_key)
            if xp is None:
                raise ValueError(f"No XP value is listed for CR {monster['cr']}.")
        else:
            raise ValueError(f"{name} needs either an XP value or a challenge rating.")

        if monster.get("cr") is not None and _cr_value(monster["cr"]) > highest_level:
            notes.append(
                f"{name} has a challenge rating above the party's level and "
                "may be able to defeat a character in a single turn."
            )

        total_xp += xp * count
        creature_count += count
        lines.append({
            "name": name,
            "count": count,
            "xp_each": xp,
            "xp_total": xp * count,
        })

    if total_xp <= budgets["Low"]:
        difficulty = "Low"
    elif total_xp <= budgets["Moderate"]:
        difficulty = "Moderate"
    elif total_xp <= budgets["High"]:
        difficulty = "High"
    else:
        difficulty = "Above High"
        notes.append("Total XP exceeds the High budget; this encounter could be lethal.")

    if creature_count > 2 * len(levels):
        notes.append(
            "There are more than two creatures per character; the DMG advises "
            "including fragile creatures that can be defeated quickly."
        )

    return {
        "party_size": len(levels),
        "party_levels": levels,
        "creatures": lines,
        "total_xp": total_xp,
        "budgets": budgets,
        "difficulty": difficulty,
        "notes": notes,
    }


@tool(args_schema=EncounterInput)
def calculate_encounter(
    party_levels: list[int],
    monsters: list[dict[str, Any]],
) -> dict[str, Any]:
    """Rate an encounter as Low, Moderate, High, or Above High using XP budgets.

    Provide one character level per party member. Each monster entry needs a name
    and count, plus XP per creature when known or its challenge rating otherwise.
    """
    return calculate_encounter_result(party_levels, monsters)
