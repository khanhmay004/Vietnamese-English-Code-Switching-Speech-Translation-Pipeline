"""Analyze manifest.tsv for data quality issues."""
import pandas as pd
import re

df = pd.read_csv('data/export/manifest.tsv', sep='\t')

print("=" * 60)
print("MANIFEST DATA QUALITY ANALYSIS")
print("=" * 60)

# Empty or very short text
empty_trans = df['transcript'].isna() | (df['transcript'].str.len() < 3)
empty_transl = df['translation'].isna() | (df['translation'].str.len() < 3)
print(f'\n=== Empty/Very Short Text ===')
print(f'Empty transcripts: {empty_trans.sum()}')
print(f'Empty translations: {empty_transl.sum()}')

# Short utterances
short_interjection = df[(df['transcript'].str.len() < 10) & (df['transcript'].str.len() > 0)]
print(f'\n=== Short Utterances (<10 chars) ===')
print(f'Count: {len(short_interjection)}')
print('Examples:')
for t in short_interjection['transcript'].head(15):
    print(f'  "{t}"')

# Check for NBSP and weird whitespace  
has_nbsp = df['transcript'].str.contains('\u00A0', na=False)
print(f'\n=== Non-Breaking Spaces ===')
print(f'Rows with NBSP: {has_nbsp.sum()}')

# Check for markdown patterns
markdown_pattern = r'\*\*[^*]+\*\*|\*[^*]+\*|\[[^\]]+\]'
has_markdown = df['transcript'].str.contains(markdown_pattern, regex=True, na=False)
print(f'\n=== Markdown Artifacts ===')
print(f'Rows with markdown: {has_markdown.sum()}')
if has_markdown.sum() > 0:
    print('Examples:')
    for t in df[has_markdown]['transcript'].head(10):
        print(f'  {t[:100]}')

# Duration distribution
print(f'\n=== Duration Distribution ===')
print(f'Total samples: {len(df)}')
print(f'Too short (<0.5s): {len(df[df.duration < 0.5])}')
print(f'Very short (0.5-1s): {len(df[(df.duration >= 0.5) & (df.duration < 1)])}')
print(f'Short (1-3s): {len(df[(df.duration >= 1) & (df.duration < 3)])}')
print(f'Medium (3-10s): {len(df[(df.duration >= 3) & (df.duration < 10)])}')
print(f'Long (10-30s): {len(df[(df.duration >= 10) & (df.duration < 30)])}')
print(f'Very long (>30s): {len(df[df.duration >= 30])}')

# Check for potential issues that need cleaning
print(f'\n=== Text Quality Summary ===')

# Leading/trailing whitespace
has_leading = df['transcript'].str.match(r'^\s+', na=False)
has_trailing = df['transcript'].str.match(r'.*\s+$', na=False)
print(f'Rows with leading whitespace: {has_leading.sum()}')
print(f'Rows with trailing whitespace: {has_trailing.sum()}')

# Multiple consecutive spaces
has_multispaces = df['transcript'].str.contains(r'\s{2,}', regex=True, na=False)
print(f'Rows with multiple spaces: {has_multispaces.sum()}')

# Check transcript = translation (no code-switching)
same_text = df['transcript'] == df['translation']
print(f'\nTranscript == Translation (no CS): {same_text.sum()} ({100*same_text.mean():.1f}%)')

print("\n" + "=" * 60)
print("ANALYSIS COMPLETE")
print("=" * 60)
