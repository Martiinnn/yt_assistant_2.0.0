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


def parse_podcast_script(text):
    """
    Parses podcast script blocks in this style:
    Parte 1 (0:00 - 0:10):
    <prompt...>
    """
    parsed_data = {"prompts": []}
    pattern = re.compile(
        r'Parte\s+(\d+)\s*\([^)]*\)\s*:\s*(.*?)(?=\n\s*Parte\s+\d+\s*\(|\Z)',
        re.IGNORECASE | re.DOTALL
    )

    for match in pattern.finditer(text):
        part_id = match.group(1).strip()
        part_text = match.group(2).strip()
        if part_text:
            parsed_data["prompts"].append({
                "id": part_id,
                "text": re.sub(r'\s+', ' ', part_text).strip()
            })

    return parsed_data
