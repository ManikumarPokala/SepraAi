"""
Script to generate the three required chemistry videos and save them to the artifacts directory.
"""

from __future__ import annotations

import os
import sys

# Ensure backend source path is in search path
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "sepraai-backend"))

from core.chemistry_generator import generate_chemistry_video

CHEMISTRY_QUERIES = [
    "How does the pH scale work?",
    "Why do atoms form covalent bonds?",
    "What is the difference between ionic and covalent bonding?"
]

def main():
    print("=== Generating Required Chemistry Concept Videos ===")
    
    # Establish local artifacts directory
    artifacts_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "artifacts/videos"))
    os.makedirs(artifacts_dir, exist_ok=True)
    
    for idx, query in enumerate(CHEMISTRY_QUERIES):
        filename = f"chemistry_concept_{idx + 1}.mp4"
        output_path = os.path.join(artifacts_dir, filename)
        
        print(f"\nRendering Video {idx + 1}: '{query}'...")
        try:
            generate_chemistry_video(query, output_path)
            print(f"Success! Saved to: {output_path} ({os.path.getsize(output_path)} bytes)")
        except Exception as e:
            print(f"Error rendering '{query}': {e}")
            
    print("\nGeneration process complete. All videos saved in 'artifacts/videos/' directory.")

if __name__ == "__main__":
    main()
