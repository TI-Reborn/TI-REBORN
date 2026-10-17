"""Insert the reviewed city page link without rebuilding unrelated content."""
from pathlib import Path

path=Path(__file__).resolve().parents[1]/'web/src/components/content-pages.tsx'
old="{user.role === 'ADMIN' && <Link"
new="""{user.gameUsername && <Link className="button button-outline" href={`/${locale}/city`}>{locale === 'ru' ? 'Банк, вещи и базы' : 'Bank, items and bases'}</Link>}{user.role === 'ADMIN' && <Link"""
source=path.read_text(encoding='utf-8')
if new not in source:
    if source.count(old)!=1:raise ValueError('Account link boundary changed')
    path.write_text(source.replace(old,new),encoding='utf-8')
