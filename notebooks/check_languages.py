import pandas as pd

df = pd.read_csv('data/sample/sample_all_20260518_104620.csv')

def detect(text):
    t = str(text).lower()
    fr = any(w in t for w in ['farine','sucre','huile','lait','arôme','arome','contient'])
    en = any(w in t for w in ['flour','sugar','oil','milk','flavour','flavor','contains'])
    if fr and not en: return 'FR'
    if en and not fr: return 'EN'
    if fr and en: return 'BOTH'
    return 'OTHER'

result = df['ingredients_text'].head(100).apply(detect).value_counts()
print(result.to_string())
print(f"\nTotal checked: 100 of {len(df)} rows")