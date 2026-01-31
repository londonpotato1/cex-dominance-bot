# -*- coding: utf-8 -*-
import pdfplumber
import os
import sys

# Keywords to search for
keywords = ["역프", "역따리", "국내 매수 해외 매도", "반대 전략", "역프리미엄", "역김프", 
            "해외 매수 국내 매도", "역", "반대", "reverse", "리버스"]

base_path = r"C:\Users\user\Documents\03_Claude\cex_dominance_bot\따리가이드"

# Find Part 03 and Part 04 folders
part_folders = []
for item in os.listdir(base_path):
    full_path = os.path.join(base_path, item)
    if os.path.isdir(full_path):
        if "Part 03" in item or "Part 04" in item:
            part_folders.append(full_path)

output_file = r"C:\Users\user\Documents\03_Claude\cex_dominance_bot\pdf_analysis_result.txt"

with open(output_file, 'w', encoding='utf-8') as f:
    f.write(f"Found {len(part_folders)} Part folders\n\n")
    
    all_results = []
    all_texts = {}
    
    for folder in part_folders:
        f.write(f"\n=== Scanning: {os.path.basename(folder)} ===\n")
        
        for root, dirs, files in os.walk(folder):
            for file in files:
                if file.endswith('.pdf'):
                    pdf_path = os.path.join(root, file)
                    f.write(f"\nProcessing: {file}\n")
                    
                    try:
                        with pdfplumber.open(pdf_path) as pdf:
                            full_text = ""
                            for page in pdf.pages:
                                text = page.extract_text()
                                if text:
                                    full_text += text + "\n"
                            
                            all_texts[file] = full_text
                            
                            # Search for keywords
                            for keyword in keywords:
                                if keyword in full_text:
                                    f.write(f"  FOUND: '{keyword}'\n")
                                    
                                    # Find all occurrences
                                    idx = 0
                                    while True:
                                        idx = full_text.find(keyword, idx)
                                        if idx == -1:
                                            break
                                        
                                        start = max(0, idx - 200)
                                        end = min(len(full_text), idx + len(keyword) + 300)
                                        context = full_text[start:end]
                                        
                                        all_results.append({
                                            'file': file,
                                            'keyword': keyword,
                                            'context': context
                                        })
                                        idx += len(keyword)
                                        
                    except Exception as e:
                        f.write(f"  Error: {str(e)}\n")

    f.write("\n\n" + "="*80 + "\n")
    f.write("SEARCH RESULTS - 역프/역따리/반대 전략 관련 내용\n")
    f.write("="*80 + "\n")

    if all_results:
        for result in all_results:
            f.write(f"\n📄 File: {result['file']}\n")
            f.write(f"🔑 Keyword: {result['keyword']}\n")
            f.write(f"📝 Context:\n{result['context']}\n")
            f.write("-"*60 + "\n")
    else:
        f.write("\n키워드를 찾지 못했습니다.\n")
    
    # Also save full text of each PDF
    f.write("\n\n" + "="*80 + "\n")
    f.write("FULL PDF CONTENTS\n")
    f.write("="*80 + "\n")
    
    for filename, text in all_texts.items():
        f.write(f"\n\n{'='*80}\n")
        f.write(f"FILE: {filename}\n")
        f.write("="*80 + "\n")
        f.write(text[:10000])  # First 10000 chars
        f.write("\n...(truncated)...\n" if len(text) > 10000 else "\n")

print(f"Results saved to: {output_file}")
