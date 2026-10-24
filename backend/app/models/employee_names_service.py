"""Owner-reviewed Uzbek Latin spelling normalization, without guessing identities."""
import re

_CYRILLIC = dict(zip('абвгдеёжзийклмнопрстуфхцчшщъыьэюяўқғҳ',
    ['a','b','v','g','d','e','yo','j','z','i','y','k','l','m','n','o','p','r','s','t','u','f','x','ts','ch','sh','shch',"'",'i','','e','yu','ya',"o'",'q',"g'",'h']))


def latin_employee_name(value: str) -> str:
    value = re.sub(r"[‘’ʻʼ`´]", "'", value.strip())
    letters = []
    for index, char in enumerate(value):
        lower = char.lower()
        if lower == 'е' and (index == 0 or value[index - 1].lower() in " аеиоуъьэюя"):
            letters.append('ye')
        else:
            letters.append(_CYRILLIC.get(lower, lower))
    value = re.sub(r'\s+', ' ', ''.join(letters))
    value = re.sub(r"'{2,}", "'", value)
    words = []
    for word in value.split():
        word = {'kizi': 'qizi', 'ogli': "o'g'li"}.get(word, word)
        words.append(word if word in {'qizi', "o'g'li"} else word[:1].upper() + word[1:])
    return ' '.join(words)
