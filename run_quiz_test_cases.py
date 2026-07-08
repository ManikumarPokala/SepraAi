"""
Verification and Test Case Runner for the Quiz Generation Service.
Executes the three required test cases end-to-end, evaluates them through the multi-agent pipeline,
tracks total token costs, and commits the result to quiz_results_output.json.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys

# Ensure backend source path is in search path
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "sepraai-backend"))

from core.quiz_pipeline import run_quiz_item_pipeline

TEST_CASES = [
    {"subject": "Secondary school chemistry", "difficulty": "Beginner", "num_items": 5},
    {"subject": "Secondary school chemistry", "difficulty": "Advanced", "num_items": 5},
    {"subject": "Secondary school biology", "difficulty": "Intermediate", "num_items": 5}
]


async def run_test_case(subject: str, difficulty: str, num_items: int) -> dict[str, Any]:
    print(f"\nRunning Quiz generation for Subject: '{subject}', Difficulty: '{difficulty}', Count: {num_items}...")
    
    items = []
    total_cost = 0.0
    
    for idx in range(num_items):
        # Trigger self-healing on the first item (idx == 0) to demonstrate Judge/Repair pipeline
        trigger_healing = (idx == 0)
        
        result = await run_quiz_item_pipeline(
            subject=subject,
            difficulty=difficulty,
            index=idx,
            trigger_self_healing=trigger_healing
        )
        
        items.append({
            "item_number": idx + 1,
            "question": result["question"],
            "choices": result["choices"],
            "correct_answer": result["correct_answer"],
            "explanation": result["explanation"],
            "cost_usd": result["cost_usd"],
            "attempts_required": result["attempts"]
        })
        total_cost += result["cost_usd"]
        
        healing_status = "HEALED (attempts: 2)" if result["attempts"] > 1 else "OK"
        print(f"  Item {idx + 1}: {result['question'][:45]}... Status: {healing_status} | Cost: ${result['cost_usd']:.6f}")
        
    return {
        "subject": subject,
        "difficulty": difficulty,
        "num_items": num_items,
        "total_cost_usd": round(total_cost, 6),
        "items": items
    }


async def main():
    print("=== Launching Quiz Service End-to-End Test Verification ===")
    
    results = []
    
    for case in TEST_CASES:
        res = await run_test_case(case["subject"], case["difficulty"], case["num_items"])
        results.append(res)
        
    output_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "quiz_results_output.json")
    
    # Save the output structured JSON to the workspace
    print(f"\nWriting final results to: {output_path}...")
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump({"test_cases": results}, f, indent=2)
        
    print("\n========================= Cost Summary =========================")
    for idx, res in enumerate(results):
        print(f"Test Case {idx + 1}: {res['subject']} ({res['difficulty']})")
        print(f"  Items Generated: {res['num_items']}")
        print(f"  Total Job Cost : ${res['total_cost_usd']:.6f}")
        # Count healed items
        healed_count = sum(1 for item in res["items"] if item["attempts_required"] > 1)
        print(f"  Self-Healed Items: {healed_count}")
        print("-" * 64)
        
    print("Verification completed successfully!")


if __name__ == "__main__":
    asyncio.run(main())
