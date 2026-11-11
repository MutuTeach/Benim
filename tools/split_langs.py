#!/usr/bin/env python3
"""Dil ayırıcı: çok dilli (span.es/.en/.pt) HTML'den tek dilli sayfalar üretir.
Kullanım: python3 tools/split_langs.py   (repo kökünden)
- fuente/index.html  -> index.html (ES) · en/index.html · pt/index.html
- blog/index.html ve blog/*/index.html (üretici çıktısı, çok dilli) -> yerinde ES + en/blog/... kopyası
Yalnız .en span'ı olan dosyalar işlenir; zaten ayrılmış dosyalar atlanır (idempotent).
"""
import re, os, glob, json, html, sys
ROOT=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
BASE='https://www.umutsimsek.co'
OPEN=re.compile(r'<span class="(es|en|pt)">')
TAG=re.compile(r'<span\b[^>]*>|</span>')

def match_end(s,i):
    """i = index right after an opening <span ...>; returns index of the matching </span> start and end."""
    depth=1; pos=i
    while True:
        m=TAG.search(s,pos)
        if not m: raise ValueError('unbalanced span')
        if m.group(0).startswith('</'): depth-=1
        else: depth+=1
        if depth==0: return m.start(), m.end()
        pos=m.end()

def pick(s,L):
    """Keep language L: unwrap L spans, drop other language spans; es fallback when L missing in a group."""
    out=[]; pos=0
    while True:
        m=OPEN.search(s,pos)
        if not m: out.append(s[pos:]); break
        out.append(s[pos:m.start()])
        # parse group of consecutive language spans
        group={}; order=[]; p=m.start()
        while True:
            mm=OPEN.match(s,p)
            if not mm: break
            a,b=match_end(s,mm.end())
            group[mm.group(1)]=s[mm.end():a]; order.append(mm.group(1))
            p=b
            # allow whitespace between sibling spans
            q=p
            while q<len(s) and s[q] in ' \n\t': q+=1
            if OPEN.match(s,q) and OPEN.match(s,q).group(1) not in group: p=q
            else: break
        chosen=group.get(L, group.get('es', group.get(order[0])))
        out.append(chosen); pos=p
    return ''.join(out)

def text(h): return html.unescape(re.sub(r'<[^>]+>','',h)).strip()

def short(t,n=155):
    t=re.sub(r'\s+',' ',t).strip()
    if len(t)<=n: return t
    parts=re.split(r'(?<=[.!?])\s+',t); acc=''
    for p in parts:
        if len(acc)+len(p)+1>n: break
        acc=(acc+' '+p).strip()
    return acc if acc else t[:n].rsplit(' ',1)[0]

def fit(t,n=162):
    """Meta description: tam cümlelerle n karaktere sığdır; çok kısa kalırsa kelime sınırında kes."""
    t=re.sub(r'\s+',' ',t).strip()
    if len(t)<=n: return t
    r=short(t,n)
    if len(r)>=100 and r[-1] in '.!?': return r
    return t[:n-1].rsplit(' ',1)[0].rstrip(',;:')+'…'

def set_meta(h,name,val,prop=False):
    key='property' if prop else 'name'
    return re.sub(rf'<meta {key}="{name}" content="[^"]*"',f'<meta {key}="{name}" content="{val.replace(chr(34),'&quot;')}"',h)

def transform(src,L,es_url,urls,titles,descs,links_map):
    """src: multilingual html; L: target; urls: {lang:url}; titles/descs: {lang:str}; links_map: func(href)->href"""
    h=pick(src,L)
    # h1 data-es/en
    def h1fix(m):
        attrs=m.group(1); inner=m.group(2)
        d=dict(re.findall(r'data-(es|en|pt)="([^"]*)"',attrs))
        attrs=re.sub(r'\s*data-(es|en|pt)="[^"]*"','',attrs)
        return f'<h1{attrs}>{d.get(L,d.get("es",inner))}</h1>'
    h=re.sub(r'<h1([^>]*)>(.*?)</h1>',h1fix,h,flags=re.S)
    # html lang, locale
    h=re.sub(r'<html lang="[^"]*"',f'<html lang="{ {"es":"es","en":"en","pt":"pt-BR"}[L] }"',h,1)
    h=re.sub(r'<meta property="og:locale" content="[^"]*"',f'<meta property="og:locale" content="{ {"es":"es_LA","en":"en_US","pt":"pt_BR"}[L] }"',h,1)
    # title/desc
    if titles.get(L):
        h=re.sub(r'<title>[^<]*</title>',f'<title>{titles[L]}</title>',h,1)
        h=set_meta(h,'og:title',titles[L],True); h=set_meta(h,'twitter:title',titles[L])
    if descs.get(L):
        h=set_meta(h,'description',descs[L]); h=set_meta(h,'og:description',descs[L],True); h=set_meta(h,'twitter:description',descs[L])
    # canonical / og:url
    h=re.sub(r'<link rel="canonical" href="[^"]*"',f'<link rel="canonical" href="{urls[L]}"',h,1)
    h=re.sub(r'<meta property="og:url" content="[^"]*"',f'<meta property="og:url" content="{urls[L]}"',h,1)
    # hreflang (replace any existing block)
    h=re.sub(r'\n?<link rel="alternate" hreflang="[^"]*" href="[^"]*">','',h)
    hl=''.join(f'\n<link rel="alternate" hreflang="{ {"es":"es","en":"en","pt":"pt-BR"}[k] }" href="{v}">' for k,v in urls.items())+f'\n<link rel="alternate" hreflang="x-default" href="{urls["es"]}">'
    h=h.replace('<link rel="canonical"',hl.lstrip('\n')+'\n<link rel="canonical"',1)
    # JSON-LD
    def ldfix(m):
        try: d=json.loads(m.group(1))
        except Exception: return m.group(0)
        t=d.get('@type')
        if t=='FAQPage' and L!='es': return ''
        if t=='Article':
            d['inLanguage']=L; d['mainEntityOfPage']=urls[L]
            if titles.get(L): d['headline']=titles[L].split(' | ')[0]
            if descs.get(L): d['description']=descs[L]
        if t=='BreadcrumbList':
            names={'es':('Inicio','Blog'),'en':('Home','Blog'),'pt':('Início','Blog')}[L]
            for it in d.get('itemListElement',[]):
                it['item']=links_map(it['item']) if it['item'].startswith(BASE) else it['item']
                if it['position']==1: it['name']=names[0]
                elif it['position']==2 and it['name']=='Blog': it['name']=names[1]
                elif it['position']==max(x['position'] for x in d['itemListElement']) and titles.get(L): it['name']=titles[L].split(' | ')[0]
        if isinstance(d.get('@graph'),list):
            for g in d['@graph']:
                if g.get('@type')=='Organization': g['inLanguage']=L
        return '<script type="application/ld+json">'+json.dumps(d,ensure_ascii=False)+'</script>'
    h=re.sub(r'<script type="application/ld\+json">(.*?)</script>',ldfix,h,flags=re.S)
    h=re.sub(r"try\{if\(localStorage\.getItem\('ibinv-lang'\)==='en'\)L\('en'\)\}catch\(x\)\{\}",'',h)
    # internal links
    h=re.sub(r'href="(/[^"#]*)"',lambda m:f'href="{links_map(m.group(1))}"',h)
    # language toggle -> links
    def btn(m):
        lang=m.group(1); on=' class="on"' if lang==L else ''
        target=urls.get(lang); 
        if not target: return ''
        return f'<a id="btn-{lang}"{on} href="{target.replace(BASE,"")}" lang="{ {"es":"es","en":"en","pt":"pt-BR"}[lang] }" aria-pressed="{"true" if lang==L else "false"}">{lang.upper()}</a>'
    h=re.sub(r'<button id="btn-(es|en|pt)"[^>]*>\s*(?:ES|EN|PT)\s*</button>',btn,h)
    h=h.replace('.lang-toggle button{','.lang-toggle button,.lang-toggle a{text-decoration:none;').replace('.lang-toggle button.on','.lang-toggle button.on,.lang-toggle a.on')
    # JS: fixed language, no auto-switch
    h=re.sub(r"if\(q\)\{setLang\(q\)\}else\{try\{var sv=localStorage\.getItem\('ibinv-lang'\);[^}]*\}catch\(x\)\{\}\}",f"setLang('{L}');",h)
    h=re.sub(r"\.addEventListener\('click',function\(\)\{setLang\('(es|en|pt)'\)\}\)",r".addEventListener('click',function(){})",h)
    return h

def write(path,content):
    os.makedirs(os.path.dirname(path) or '.',exist_ok=True)
    open(path,'w',encoding='utf-8').write(content)

def has_en(s): return '<span class="en">' in s

report=[]
# PT'si olan yazılar: çok dilli üretici çıktısında data-pt taşıyanlar + daha önce ayrılmış pt/blog/<slug>/ sayfaları
PT_POSTS={f.split('/')[1] for f in glob.glob('blog/*/index.html') if re.search(r'<h1 class="ptitle"[^>]*data-pt="', open(f,encoding='utf-8').read())}
PT_POSTS|={f.split('/')[2] for f in glob.glob('pt/blog/*/index.html')}
PT_TITLE={}; PT_DESC={}
try:
    _bi=open('blog/index.html',encoding='utf-8').read()
    for _m in re.finditer(r'<a class="card[^"]*" href="/blog/([a-z0-9-]+)/">(.*?)</a>',_bi,re.S):
        _h=re.search(r'<h3>(.*?)</h3>',_m.group(2),re.S); _p=re.search(r'<p>(.*?)</p>',_m.group(2),re.S)
        if _h and '<span class="pt">' in _h.group(1): PT_TITLE[_m.group(1)]=text(pick(_h.group(1),'pt'))
        if _p and '<span class="pt">' in _p.group(1): PT_DESC[_m.group(1)]=text(pick(_p.group(1),'pt'))
except Exception: pass
# ---------- HOME ----------
src=open('fuente/index.html',encoding='utf-8').read()
if not has_en(src): sys.exit('fuente/index.html çok dilli değil')
has_pt='<span class="pt">' in src
home_urls={'es':BASE+'/','en':BASE+'/en/'}
if has_pt: home_urls['pt']=BASE+'/pt/'
titles={'es':None,'en':'Training for forex and synthetic indices IBs | IB ACADEMY','pt':'Formação para IBs de forex e índices sintéticos | IB ACADEMY'}
descs={'es':None,'en':'Training for forex and synthetic indices IBs (Introducing Brokers) in Latin America: win, retain and organise your client portfolio as a business. No income promises.','pt':'Formação para IBs (Introducing Brokers) de forex e índices sintéticos na América Latina: conquistar, reter e organizar sua carteira como um negócio. Sem promessas de renda.'}
en_posts=set()
for L,u in home_urls.items():
    def lm(href,L=L):
        if L=='es': return href
        if L=='pt':
            if href=='/': return '/pt/'
            if href=='/blog/': return '/pt/blog/' if PT_POSTS else href
            mp=re.match(r'^/blog/([a-z0-9-]+)/$',href)
            if mp and mp.group(1) in PT_POSTS: return f'/pt/blog/{mp.group(1)}/'
            if href.startswith(BASE): return BASE+lm(href[len(BASE):],L)
            return href
        if href=='/': return '/en/'
        if href=='/blog/': return '/en/blog/'
        m=re.match(r'^/blog/([a-z0-9-]+)/$',href)
        if m and os.path.exists(f'blog/{m.group(1)}/index.html'): return f'/en/blog/{m.group(1)}/'
        if href.startswith(BASE): return BASE+lm(href[len(BASE):],L)
        return href
    out=transform(src,L,home_urls['es'],home_urls,titles,descs,lm)
    write({'es':'index.html','en':'en/index.html','pt':'pt/index.html'}[L],out)
    report.append(f'home {L}: {len(out)} bytes · es={out.count(chr(60)+"span class=\"es\">")} en={out.count(chr(60)+"span class=\"en\">")} pt={out.count(chr(60)+"span class=\"pt\">")}')

def pt_index_filter(h):
    """PT blog listesinde sadece PT sayfasi olan yazilar kalsin; numaralari yenile; JSON-LD listesini filtrele."""
    def keep(m):
        href=re.search(r'href="([^"]+)"',m.group(0)).group(1)
        mm=re.match(r'^/pt/blog/([a-z0-9-]+)/$',href)
        return m.group(0) if (mm and mm.group(1) in PT_POSTS) else ''
    h=re.sub(r'<a class="card[^"]*" href="[^"]+">.*?</a>',keep,h,flags=re.S)
    n=[0]
    def renum(m):
        n[0]+=1; return f'<span class="bnum">{n[0]}</span>'
    h=re.sub(r'<span class="bnum">\d+</span>',renum,h)
    def ldf(m):
        try: d=json.loads(m.group(1))
        except Exception: return m.group(0)
        if isinstance(d.get('blogPost'),list):
            keep2=[]
            for b in d['blogPost']:
                mm=re.search(r'/blog/([a-z0-9-]+)/',b.get('url',''))
                if mm and mm.group(1) in PT_POSTS:
                    b['url']=re.sub(r'/blog/','/pt/blog/',b['url'],1)
                    if PT_TITLE.get(mm.group(1)): b['headline']=PT_TITLE[mm.group(1)]
                    keep2.append(b)
            d['blogPost']=keep2; d['inLanguage']='pt-BR'; d['url']=BASE+'/pt/blog/'; d['name']='Blog para IBs — IB ACADEMY'
        return '<script type="application/ld+json">'+json.dumps(d,ensure_ascii=False)+'</script>'
    h=re.sub(r'<script type="application/ld\+json">(.*?)</script>',ldf,h,flags=re.S)
    # PT'si olmayan yazilara giden 'ruta' kartlarini kaldir; blok bosalirsa bolumu de kaldir
    def keepruta(m):
        href=re.search(r'href="([^"]+)"',m.group(0)).group(1)
        mm=re.match(r'^/(?:pt/)?blog/([a-z0-9-]+)/$',href)
        return m.group(0) if (mm and mm.group(1) in PT_POSTS) else ''
    h=re.sub(r'<a class="ruta"[^>]*>.*?</a>',keepruta,h,flags=re.S)
    h=re.sub(r'<div class="rutas"[^>]*>\s*</div>','',h)
    return h

# ---------- BLOG INDEX + POSTS ----------
files=['blog/index.html']+sorted(glob.glob('blog/*/index.html'))
def has_pt_post(slug):
    try: return '<span class="pt">' in open(f'blog/{slug}/index.html',encoding='utf-8').read()
    except Exception: return False
def blog_lm(href,L):
    if L=='es': return href
    if href=='/': return f'/{L}/'
    if href=='/blog/': return '/en/blog/' if L=='en' else ('/pt/blog/' if PT_POSTS else '/blog/')
    m=re.match(r'^/blog/([a-z0-9-]+)/$',href)
    if m:
        slug=m.group(1)
        if L=='en' and os.path.exists(f'en/blog/{slug}/index.html'): return f'/en/blog/{slug}/'
        if L=='pt' and PT_POSTS and slug in PT_POSTS: return f'/pt/blog/{slug}/'
        return href
    if href.startswith(BASE): return BASE+blog_lm(href[len(BASE):],L)
    return href
for f in files:
    s=open(f,encoding='utf-8').read()
    if not has_en(s): report.append(f'{f}: zaten tek dilli, atlandı'); continue
    rel='/'+f.replace('index.html','')  # /blog/ or /blog/slug/
    slug=f.split('/')[1] if f!='blog/index.html' else None
    want_pt = (slug in PT_POSTS) if slug else bool(PT_POSTS)
    urls={'es':BASE+rel,'en':BASE+'/en'+rel}
    if want_pt: urls['pt']=BASE+'/pt'+rel
    if f=='blog/index.html':
        t={'es':None,'en':'Blog for IBs: the real work of the Introducing Broker | IB ACADEMY'}
        d={'es':None,'en':'Lead generation, retention, follow-up and systems: the real work of an IB, explained without income promises.'}
    else:
        h1=re.search(r'<h1 class="ptitle"[^>]*data-en="([^"]*)"',s)
        en_title=(html.unescape(h1.group(1)) if h1 else None)
        pl=re.search(r'<p class="plead">(.*?)</p>',s,re.S)
        en_lead=text(pick(pl.group(1),'en')) if pl else ''
        t={'es':None,'en':(en_title+' | IB ACADEMY') if en_title else None}
        d={'es':None,'en':short(en_lead) if en_lead else None}
    if want_pt and f=='blog/index.html':
        t['pt']='Blog para IBs: o trabalho real do Introducing Broker | IB ACADEMY'
        d['pt']='Captação, retenção, follow-up e sistemas: o trabalho real de um IB, explicado sem promessas de ganho.'
    elif want_pt:
        h1p=re.search(r'<h1 class="ptitle"[^>]*data-pt="([^"]*)"',s)
        pt_title=(html.unescape(h1p.group(1)) if h1p else None)
        plp=re.search(r'<p class="plead">(.*?)</p>',s,re.S)
        pt_lead=text(pick(plp.group(1),'pt')) if plp else ''
        t['pt']=(pt_title+' | IB ACADEMY') if pt_title else None
        d['pt']=(fit(PT_DESC[slug]) if PT_DESC.get(slug) else None) or (short(pt_lead) if pt_lead else None)
    langs=('es','en','pt') if want_pt else ('es','en')
    for L in langs:
        out=transform(s,L,urls['es'],urls,t,d,lambda href,L=L:blog_lm(href,L))
        if L=='pt' and f=='blog/index.html':
            out=pt_index_filter(out)
        write({'es':f,'en':'en/'+f,'pt':'pt/'+f}[L],out)
    report.append(f'{f}: es yerinde + en/{f}'+(' + pt/'+f if want_pt else ''))
# ---------- SITEMAP ----------
sm=open('sitemap.xml',encoding='utf-8').read()
existing=set(re.findall(r'<loc>([^<]+)</loc>',sm))
add=[]
for u in [BASE+'/en/']+([BASE+'/pt/'] if has_pt else [])+[BASE+'/en/blog/']+[BASE+'/en/blog/'+d.split('/')[1]+'/' for d in sorted(glob.glob('blog/*/')) if os.path.exists('en/'+d+'index.html')]+([BASE+'/pt/blog/'] if os.path.exists('pt/blog/index.html') else [])+[BASE+'/pt/blog/'+d.split('/')[1]+'/' for d in sorted(glob.glob('blog/*/')) if os.path.exists('pt/'+d+'index.html')]:
    if u not in existing:
        _es=u.replace(BASE+'/en/',BASE+'/').replace(BASE+'/pt/',BASE+'/')
        _lm=re.search(r'<loc>'+re.escape(_es)+r'</loc><lastmod>([^<]+)</lastmod>',sm)
        add.append(f'  <url><loc>{u}</loc><lastmod>{_lm.group(1) if _lm else "2026-11-03"}</lastmod><priority>0.6</priority></url>')
if add:
    sm=sm.replace('</urlset>','\n'.join(add)+'\n</urlset>'); open('sitemap.xml','w',encoding='utf-8').write(sm)
report.append(f'sitemap +{len(add)}')
print('\n'.join(report))
