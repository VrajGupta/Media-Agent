def clean_mojibake(text: str) -> str:
    return text.replace("�", "'")
