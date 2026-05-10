import re

def parse_script(text):
    """
    Parses a raw script from Gemini into structured data.
    Extracts Phrases and Prompts.
    """
    lines = text.split('\n')
    
    parsed_data = {
        "phrases": [],
        "prompts": []
    }
    
    current_phrase_id = None
    
    for line in lines:
        line = line.strip()
        if not line:
            continue
            
        # Match phrase, e.g., "Frase 7: Nivel 1. El Niño Prodigio..."
        phrase_match = re.match(r'Frase\s+(\d+):\s+(.*)', line, re.IGNORECASE)
        if phrase_match:
            phrase_id = phrase_match.group(1)
            phrase_text = phrase_match.group(2).strip()
            parsed_data["phrases"].append({
                "id": phrase_id,
                "text": phrase_text
            })
            current_phrase_id = phrase_id
            continue
            
        # Match prompt, e.g., "Prompt 7: The young main character..."
        prompt_match = re.match(r'Prompt\s+(\d+):\s+(.*)', line, re.IGNORECASE)
        if prompt_match:
            prompt_id = prompt_match.group(1)
            prompt_text = prompt_match.group(2).strip()
            parsed_data["prompts"].append({
                "id": prompt_id,
                "text": prompt_text
            })
            continue

    return parsed_data
