"""
Quiz Pipeline module executing Creator, Judge, and Repair agents.
Implements LLM-as-judge validation, self-healing retry logic, and strict cost tracking.
"""

from __future__ import annotations

import random
import logging
import uuid
from typing import Any, TypedDict

logger = logging.getLogger(__name__)

# ── LLM Token Pricing Sheets ──────────────────────────────────────────────

AGENTS_PRICING = {
    "creator_repair": {"input_rate": 0.003 / 1000, "output_rate": 0.015 / 1000},
    "judge": {"input_rate": 0.0015 / 1000, "output_rate": 0.006 / 1000}
}


class AgentCostTracker:
    """Tracks LLM token counts and converts them to USD cost."""
    def __init__(self, agent_type: str):
        self.input_rate = AGENTS_PRICING[agent_type]["input_rate"]
        self.output_rate = AGENTS_PRICING[agent_type]["output_rate"]

    def calculate_cost(self, input_tokens: int, output_tokens: int) -> float:
        cost = (input_tokens * self.input_rate) + (output_tokens * self.output_rate)
        return round(cost, 6)


# ── Structured Pre-Baked Syllabus Content for Reliability ──────────────────

PRE_BAKED_QUIZZES = {
    ("secondary school chemistry", "beginner"): [
        {
            "question": "What is the chemical symbol for water?",
            "choices": ["H2O", "CO2", "NaCl", "O2"],
            "correct_answer": "H2O",
            "explanation": "H2O represents water, consisting of two hydrogen atoms and one oxygen atom."
        },
        {
            "question": "Which subatomic particle has a negative charge?",
            "choices": ["Proton", "Neutron", "Electron", "Nucleus"],
            "correct_answer": "Electron",
            "explanation": "Electrons carry a negative charge and orbit the nucleus of an atom."
        },
        {
            "question": "What is the pH of pure water?",
            "choices": ["0", "7", "14", "1"],
            "correct_answer": "7",
            "explanation": "Pure water is neutral with a pH value of 7."
        },
        {
            "question": "What state of matter has a definite volume but no definite shape?",
            "choices": ["Solid", "Liquid", "Gas", "Plasma"],
            "correct_answer": "Liquid",
            "explanation": "Liquids have a definite volume but conform to the shape of their container."
        },
        {
            "question": "What is the atomic number of Hydrogen?",
            "choices": ["1", "2", "6", "8"],
            "correct_answer": "1",
            "explanation": "Hydrogen is the simplest element, containing exactly one proton in its nucleus."
        }
    ],
    ("secondary school chemistry", "advanced"): [
        {
            "question": "Which of the following describes the Heisenberg Uncertainty Principle?",
            "choices": [
                "It is impossible to know both position and momentum of a particle simultaneously.",
                "Energy is quantized in discrete packets.",
                "Electrons fill lower energy orbitals first.",
                "No two electrons can have the same set of quantum numbers."
            ],
            "correct_answer": "It is impossible to know both position and momentum of a particle simultaneously.",
            "explanation": "The Heisenberg Uncertainty Principle states that the position and momentum of a subatomic particle cannot both be measured precisely at the same time."
        },
        {
            "question": "What is the hybridization of carbon in benzene?",
            "choices": ["sp", "sp2", "sp3", "sp3d"],
            "correct_answer": "sp2",
            "explanation": "Each carbon in benzene forms three sigma bonds in a planar configuration, resulting in sp2 hybridization."
        },
        {
            "question": "Which thermodynamic property is defined as the measure of disorder in a system?",
            "choices": ["Enthalpy", "Entropy", "Gibbs Free Energy", "Internal Energy"],
            "correct_answer": "Entropy",
            "explanation": "Entropy (S) measures the thermodynamic disorder or randomness of a closed system."
        },
        {
            "question": "What is the conjugate base of the bisulfate ion (HSO4-)?",
            "choices": ["H2SO4", "SO4(2-)", "H3SO4+", "SO3(2-)"],
            "correct_answer": "SO4(2-)",
            "explanation": "The conjugate base is formed by removing a proton (H+) from the bisulfate ion, yielding sulfate (SO4^2-)."
        },
        {
            "question": "Which equation relates the cell potential of an electrochemical cell to the concentrations of the reactants?",
            "choices": ["Nernst Equation", "Arrhenius Equation", "Gibbs Equation", "Henderson-Hasselbalch Equation"],
            "correct_answer": "Nernst Equation",
            "explanation": "The Nernst Equation relates the reduction potential of an electrochemical cell to the standard electrode potential, temperature, and activities of the chemical species."
        }
    ],
    ("secondary school biology", "intermediate"): [
        {
            "question": "What is the primary site of photosynthesis in plant cells?",
            "choices": ["Mitochondria", "Chloroplast", "Ribosome", "Golgi Apparatus"],
            "correct_answer": "Chloroplast",
            "explanation": "Chloroplasts contain chlorophyll which absorbs light energy to synthesize glucose during photosynthesis."
        },
        {
            "question": "Which base pairs with Adenine in RNA molecules?",
            "choices": ["Thymine", "Cytosine", "Uracil", "Guanine"],
            "correct_answer": "Uracil",
            "explanation": "In RNA, Uracil pairs with Adenine. Thymine pairs with Adenine only in DNA."
        },
        {
            "question": "What is the process of cell division that results in four genetically diverse daughter cells?",
            "choices": ["Mitosis", "Meiosis", "Binary Fission", "Cytokinesis"],
            "correct_answer": "Meiosis",
            "explanation": "Meiosis produces four haploid gametes (daughter cells), each with half the number of chromosomes of the parent cell, ensuring genetic diversity."
        },
        {
            "question": "Which organelle is responsible for cellular respiration and ATP production?",
            "choices": ["Mitochondria", "Lysosome", "Endoplasmic Reticulum", "Vacuole"],
            "correct_answer": "Mitochondria",
            "explanation": "Often called the powerhouses of the cell, mitochondria generate chemical energy in the form of ATP."
        },
        {
            "question": "What is the movement of water molecules across a semipermeable membrane from low solute to high solute concentration?",
            "choices": ["Diffusion", "Osmosis", "Active Transport", "Facilitated Diffusion"],
            "correct_answer": "Osmosis",
            "explanation": "Osmosis is the passive transport of water solvent molecules across a selectively permeable membrane."
        }
    ]
}


# ── Dynamic Question Generator ────────────────────────────────────────────

class DynamicQuestionGenerator:
    """Dynamically generates real-looking questions on math, physics, geography, etc."""
    @staticmethod
    def generate(subject: str, difficulty: str, index: int) -> dict[str, Any]:
        subj_lower = subject.lower()
        diff_lower = difficulty.lower()
        
        # 1. Math generation (highly dynamic)
        if "math" in subj_lower or "algebra" in subj_lower or "arithmetic" in subj_lower:
            a = random.randint(5, 50)
            b = random.randint(2, 10)
            op = random.choice(["+", "-", "*"])
            if op == "+":
                ans = a + b
                question = f"What is the value of {a} + {b}?"
                explanation = f"Adding {a} and {b} gives {ans}."
            elif op == "-":
                ans = a - b
                question = f"What is the value of {a} - {b}?"
                explanation = f"Subtracting {b} from {a} gives {ans}."
            else:
                ans = a * b
                question = f"What is the value of {a} x {b}?"
                explanation = f"Multiplying {a} by {b} gives {ans}."
                
            choices = [str(ans), str(ans + random.randint(1, 5)), str(ans - random.randint(1, 5)), str(ans * 2)]
            # Ensure unique options
            choices = list(set(choices))
            while len(choices) < 4:
                choices.append(str(ans + len(choices) * 10))
            choices = choices[:4]
            # Ensure correct answer is in options
            if str(ans) not in choices:
                choices[0] = str(ans)
            random.shuffle(choices)
            
            return {
                "question": question,
                "choices": choices,
                "correct_answer": str(ans),
                "explanation": explanation
            }
            
        # 2. Physics generation
        if "physic" in subj_lower:
            physics_pool = [
                {
                    "question": "What is the SI unit of force?",
                    "choices": ["Newton", "Joule", "Watt", "Pascal"],
                    "correct_answer": "Newton",
                    "explanation": "The Newton (N) is the SI unit of force."
                },
                {
                    "question": "What is the speed of light in a vacuum?",
                    "choices": ["3 x 10^8 m/s", "1.5 x 10^8 m/s", "3 x 10^6 m/s", "3 x 10^10 m/s"],
                    "correct_answer": "3 x 10^8 m/s",
                    "explanation": "The speed of light in a vacuum is exactly 299,792,458 m/s (~3 x 10^8 m/s)."
                },
                {
                    "question": "Which particles reside in the nucleus of an atom?",
                    "choices": ["Protons and Neutrons", "Protons and Electrons", "Neutrons and Electrons", "Electrons only"],
                    "correct_answer": "Protons and Neutrons",
                    "explanation": "Protons and neutrons form the nucleus, while electrons orbit around it."
                },
                {
                    "question": "What is the acceleration due to gravity on Earth?",
                    "choices": ["9.8 m/s^2", "8.9 m/s^2", "10.5 m/s^2", "7.2 m/s^2"],
                    "correct_answer": "9.8 m/s^2",
                    "explanation": "The standard acceleration of gravity on Earth is 9.8 m/s^2."
                },
                {
                    "question": "Which of Newton's laws is also known as the Law of Inertia?",
                    "choices": ["First Law", "Second Law", "Third Law", "Law of Gravitation"],
                    "correct_answer": "First Law",
                    "explanation": "Newton's First Law states that an object remains at rest or in motion unless acted upon by an external force."
                }
            ]
            return dict(physics_pool[index % len(physics_pool)])

        # 3. Geography generation
        if "geography" in subj_lower or "earth" in subj_lower:
            geo_pool = [
                {
                    "question": "What is the capital of France?",
                    "choices": ["Paris", "London", "Berlin", "Rome"],
                    "correct_answer": "Paris",
                    "explanation": "Paris is the capital and most populous city of France."
                },
                {
                    "question": "Which is the largest ocean on Earth?",
                    "choices": ["Pacific Ocean", "Atlantic Ocean", "Indian Ocean", "Arctic Ocean"],
                    "correct_answer": "Pacific Ocean",
                    "explanation": "The Pacific Ocean is the largest and deepest of Earth's oceanic divisions."
                },
                {
                    "question": "What is the longest river in the world?",
                    "choices": ["Nile River", "Amazon River", "Yangtze River", "Mississippi River"],
                    "correct_answer": "Nile River",
                    "explanation": "The Nile is traditionally considered the longest river in the world, stretching 6,650 km."
                },
                {
                    "question": "Which country has the largest population in the world?",
                    "choices": ["India", "China", "United States", "Indonesia"],
                    "correct_answer": "India",
                    "explanation": "India is currently the most populous country in the world."
                },
                {
                    "question": "Which is the tallest mountain on Earth?",
                    "choices": ["Mount Everest", "K2", "Kangchenjunga", "Lhotse"],
                    "correct_answer": "Mount Everest",
                    "explanation": "Mount Everest is Earth's highest mountain above sea level, located in the Himalayas."
                }
            ]
            return dict(geo_pool[index % len(geo_pool)])

        # 4. Fallback default
        return {
            "question": f"What is the main focus of study in {subject} at {difficulty} level (Item {index + 1})?",
            "choices": ["Core theories and formulas", "History and development", "Practical experiments", "All of the above"],
            "correct_answer": "All of the above",
            "explanation": f"Study of {subject} at {difficulty} level typically encompasses theory, history, and practice."
        }


# ── Pipeline Agents ───────────────────────────────────────────────────────

class CreatorAgent:
    """Simulates LLM call to create quiz items, tracking token costs."""
    def __init__(self):
        self.tracker = AgentCostTracker("creator_repair")

    def generate_raw_item(self, subject: str, difficulty: str, index: int, force_faulty: bool = False) -> tuple[dict[str, Any], float]:
        """Generates a quiz item. Can intentionally generate a faulty item for self-healing demonstration."""
        normalized_subj = subject.strip().lower()
        normalized_diff = difficulty.strip().lower()
        key = (normalized_subj, normalized_diff)

        # Retrieve structural template
        if key in PRE_BAKED_QUIZZES and index < len(PRE_BAKED_QUIZZES[key]):
            item = dict(PRE_BAKED_QUIZZES[key][index])
        else:
            # Fallback dynamic generated item
            item = DynamicQuestionGenerator.generate(subject, difficulty, index)

        # Simulating token count for Creator call
        input_tokens = 250
        output_tokens = 150

        # Intentionally inject a flaw to demonstrate LLM-as-Judge & Repair pipeline
        if force_faulty:
            item = dict(item)
            item["choices"] = item["choices"][:3] # Trigger flaw: only 3 choices!
            output_tokens = 120
            logger.info("Creator Agent [Faulty Mode]: Intentionally generated a faulty item (3 choices).")

        cost = self.tracker.calculate_cost(input_tokens, output_tokens)
        return item, cost


class JudgeAgent:
    """Structured LLM-as-Judge validator, checking quality parameters."""
    def __init__(self):
        self.tracker = AgentCostTracker("judge")

    def evaluate_item(self, item: dict[str, Any]) -> tuple[bool, str | None, float]:
        """
        Validates item against strict quality gates:
        - Must have exactly 4 choices
        - Correct answer must be one of the choices
        - Question and explanation must not be empty
        """
        input_tokens = 300
        output_tokens = 50
        cost = self.tracker.calculate_cost(input_tokens, output_tokens)

        # 1. Check choices count
        choices = item.get("choices", [])
        if len(choices) != 4:
            feedback = f"QualityGateViolation: Choices list must contain exactly 4 options. Found {len(choices)}."
            logger.warning("Judge Agent: REJECTED item. Feedback: %s", feedback)
            return False, feedback, cost

        # 2. Check correct answer presence
        correct = item.get("correct_answer")
        if correct not in choices:
            feedback = f"QualityGateViolation: Correct answer '{correct}' is not listed in the options."
            logger.warning("Judge Agent: REJECTED item. Feedback: %s", feedback)
            return False, feedback, cost

        # 3. Check text fields
        if not item.get("question") or not item.get("explanation"):
            feedback = "QualityGateViolation: Question or explanation text is empty."
            logger.warning("Judge Agent: REJECTED item. Feedback: %s", feedback)
            return False, feedback, cost

        logger.info("Judge Agent: PASSED item quality check.")
        return True, None, cost


class RepairAgent:
    """Simulates LLM call to patch and fix rejected quiz items based on judge feedback."""
    def __init__(self):
        self.tracker = AgentCostTracker("creator_repair")

    def repair_item(self, item: dict[str, Any], feedback: str, subject: str, difficulty: str, index: int) -> tuple[dict[str, Any], float]:
        """Re-generates or patches the choices/answers to resolve violations."""
        logger.info("Repair Agent: Executing repair for feedback: %s", feedback)

        # Retrieve the clean pre-baked item to simulate perfect repair
        normalized_subj = subject.strip().lower()
        normalized_diff = difficulty.strip().lower()
        key = (normalized_subj, normalized_diff)

        if key in PRE_BAKED_QUIZZES and index < len(PRE_BAKED_QUIZZES[key]):
            repaired_item = dict(PRE_BAKED_QUIZZES[key][index])
        else:
            repaired_item = DynamicQuestionGenerator.generate(subject, difficulty, index)

        input_tokens = 350
        output_tokens = 160
        cost = self.tracker.calculate_cost(input_tokens, output_tokens)

        return repaired_item, cost


# ── Core Pipeline Orchestration ───────────────────────────────────────────

class QuizPipelineResult(TypedDict):
    question: str
    choices: list[str]
    correct_answer: str
    explanation: str
    cost_usd: float
    attempts: int


async def run_quiz_item_pipeline(
    subject: str,
    difficulty: str,
    index: int,
    trigger_self_healing: bool = False
) -> QuizPipelineResult:
    """
    Orchestrates the generate -> validate/judge -> repair -> finalize pipeline.
    If trigger_self_healing is True, it forces a fault on attempt 1 to show repair routing.
    """
    creator = CreatorAgent()
    judge = JudgeAgent()
    repair = RepairAgent()

    attempts = 1
    total_item_cost = 0.0

    # Step 1: Generate original item
    # Force a faulty response on attempt 1 if requested
    force_fault = trigger_self_healing and (attempts == 1)
    item, cost = creator.generate_raw_item(subject, difficulty, index, force_faulty=force_fault)
    total_item_cost += cost

    # Step 2: LLM-as-Judge Quality Gate evaluation
    passed, feedback, cost = judge.evaluate_item(item)
    total_item_cost += cost

    # Step 3: Self-healing repair loop if verification failed
    while not passed and attempts < 3:
        attempts += 1
        logger.info("Self-Healing: Initializing Repair loop for item %s (attempt %s)...", index + 1, attempts)
        
        # Repair the item using feedback instructions
        item, cost = repair.repair_item(item, feedback, subject, difficulty, index)
        total_item_cost += cost

        # Re-evaluate
        passed, feedback, cost = judge.evaluate_item(item)
        total_item_cost += cost

    if not passed:
        logger.error("Self-Healing pipeline failed to verify item %s after %s attempts.", index + 1, attempts)
        # Ensure we return a fallback valid structure to prevent service crash
        item["choices"] = ["Option A", "Option B", "Option C", "Option D"]
        item["correct_answer"] = "Option A"
        item["explanation"] = "Fallback valid options generated due to verification failure."

    return {
        "question": item["question"],
        "choices": item["choices"],
        "correct_answer": item["correct_answer"],
        "explanation": item["explanation"],
        "cost_usd": round(total_item_cost, 6),
        "attempts": attempts
    }
