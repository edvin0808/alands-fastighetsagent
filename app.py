import re, sqlite3, hashlib, io, json
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse
import pandas as pd
import requests
from bs4 import BeautifulSoup
from pypdf import PdfReader
from parser_fix import extract
import streamlit as st
import plotly.express as px

st.set_page_config(page_title='Åland | Fastighetsanalys', page_icon='⌂', layout='wide')
st.markdown("""<style>
.stApp {background:#F2F5F3;color:#23343C}
.block-container {max-width:1380px;padding-top:1.7rem}
h1,h2,h3 {color:#23343C;letter-spacing:-.025em}
[data-testid="stSidebar"] {background:#E5ECE9}
[data-testid="stMetric"] {background:#FFFFFF;border:1px solid #D3DEDA;border-radius:14px;padding:16px}
[data-testid="stMetricValue"] {color:#245B50}
div[data-testid="stVerticalBlockBorderWrapper"] {border-radius:14px}
</style>""", unsafe_allow_html=True)
DB='fastighetsagent.db'
SOURCES={'Mäklarhuset Åland':'https://www.maklarhuset.ax/objekt-till-salu','Lyyski Fastigheter':'https://lyyski.ax/objekt/'}
REGIONS={'Mariehamn':13.41,'Landsbygd':10.80,'Skärgård':9.77}
MUNICIPALITIES=['Mariehamn','Jomala','Finström','Lemland','Hammarland','Saltvik','Sund','Eckerö','Geta','Vårdö','Föglö','Kumlinge','Kökar','Sottunga','Brändö','Lumparland']
ISLANDS={'Vårdö','Föglö','Kumlinge','Kökar','Sottunga','Brändö'}

def db():
 c=sqlite3.connect(DB);c.execute('''CREATE TABLE IF NOT EXISTS objects (id TEXT PRIMARY KEY, title TEXT, municipality TEXT, category TEXT, price REAL, debtfree REAL, area REAL, fee REAL, url TEXT, source TEXT, description TEXT, updated TEXT)''');c.execute('''CREATE TABLE IF NOT EXISTS history (id TEXT, seen TEXT, price REAL, debtfree REAL)''');c.commit();return c

def amount(s):
 s=re.sub(r'[^\d,. ]','',str(s)).strip().replace(' ','').replace('\xa0','')
 if not s:return None
 if ',' in s and '.' in s:s=s.replace('.','').replace(',','.')
 elif ',' in s:s=s.replace(',','.')
 elif s.count('.')==1 and len(s.split('.')[-1])==3:s=s.replace('.','')
 try:return float(s)
 except:return None

def matchmoney(t,patterns):
 for p in patterns:
  m=re.search(p,t,re.I)
  if m:return amount(m.group(1))
 return None

def robots_ok(url):
 from urllib.robotparser import RobotFileParser
 p=urlparse(url)
 robots_url=f'{p.scheme}://{p.netloc}/robots.txt'
 try:
  response=requests.get(robots_url,timeout=15,headers={'User-Agent':'AlandsFastighetsAgent/1.0'})
  response.raise_for_status()
  parser=RobotFileParser()
  parser.parse(response.text.splitlines())
  return parser.can_fetch('AlandsFastighetsAgent/1.0',url)
 except Exception as e:
  raise RuntimeError(f'Robots-kontrollen misslyckades: {e}')

def fetch(url):
 if not robots_ok(url):raise RuntimeError('robots.txt kunde inte verifieras eller tillåter inte hämtning')
 r=requests.get(url,headers={'User-Agent':'AlandsFastighetsAgent/1.0 (private research)'},timeout=18);r.raise_for_status()
 if len(r.content)>3_000_000:raise ValueError('Sidan är för stor')
 return BeautifulSoup(r.text,'html.parser')

CATEGORIES=['Lägenhet','Egnahemshus/villa','Radhus/parhus','Fritidshus','Tomt/mark','Industri/lager','Kommersiell/företag','Hyresobjekt','Hus/övrigt']

def category(t):
 s=(t or '').lower()
 if any(x in s for x in ['hyreslägenhet','uthyres','hyresobjekt']):return 'Hyresobjekt'
 if any(x in s for x in ['industri','lager','verkstad','produktionslokal']):return 'Industri/lager'
 if any(x in s for x in ['kontor','affärsfastighet','butikslokal','restaurang','hotell','företagsfastighet']):return 'Kommersiell/företag'
 if any(x in s for x in ['tomt','markområde','byggnadsrätt']):return 'Tomt/mark'
 if any(x in s for x in ['radhus','parhus']):return 'Radhus/parhus'
 if any(x in s for x in ['fritid','stuga','sommarställe']):return 'Fritidshus'
 if any(x in s for x in ['lägenhet','tvåa','trea','fyra','etta','aktielägenhet','bostadsaktie']):return 'Lägenhet'
 if any(x in s for x in ['egnahem','villa','bostadshus','enfamiljshus']):return 'Egnahemshus/villa'
 return 'Hus/övrigt'

def parse_detail(url,source):
 soup=fetch(url)
 item=extract(str(soup),url)
 return {'id':hashlib.sha256(url.encode()).hexdigest()[:20],
         'title':item['title'][:160], 'municipality':item['municipality'],
         'category':category(item['title']+' '+item['description'][:1000]),
         'price':item['price'],'debtfree':item['debtfree'],
         'area':item['area'],'fee':item['fee'],
         'url':url,'source':source,'description':item['description'],
         'updated':datetime.now(timezone.utc).isoformat()}

def links_from_index(url):
 soup=fetch(url);base=urlparse(url).netloc;out=[]
 for a in soup.select('a[href]'):
  u=urljoin(url,a['href']);p=urlparse(u)
  if p.netloc!=base:continue
  path=p.path.lower().rstrip('/')
  if 'maklarhuset' in base and not (path.startswith('/objekt-till-salu/') or path.startswith('/objekt/')):continue
  if 'lyyski' in base and not (path.startswith('/objekt/') and path!='/objekt'):continue
  if u not in out:out.append(u)
 return out

def save(item):
 c=db();old=c.execute('SELECT price,debtfree FROM objects WHERE id=?',(item['id'],)).fetchone()
 cols=list(item);c.execute('INSERT OR REPLACE INTO objects ('+','.join(cols)+') VALUES ('+','.join(['?']*len(cols))+')',list(item.values()))
 if old is None or old!=(item['price'],item['debtfree']):c.execute('INSERT INTO history VALUES (?,?,?,?)',(item['id'],item['updated'],item['price'],item['debtfree']))
 c.commit();c.close()

def data():
 c=db();d=pd.read_sql_query('SELECT * FROM objects',c);c.close();return d

def rent_estimate(mun,area,typ):
 if not area or area<=0 or typ in ('Tomt/mark','Kommersiell/företag','Industri/lager'):return None
 region='Mariehamn' if mun=='Mariehamn' else ('Skärgård' if mun in ISLANDS else 'Landsbygd')
 base=REGIONS[region]*area
 return (round(base*.8),round(base),round(base*1.2),region)

def risk_analysis(text):
 rules=[('Fukt eller vatten',r'fukt|vattenskad|läckage|mögel'),('Tak',r'tak(?:et|byte|renovering)|yttertak'),('VVS och avlopp',r'avlopp|stambyt|vattenledningar'),('Ytskikt',r'ytskikt|renoveringsbehov|uppfräschning'),('Fönster',r'fönsterbyte|äldre fönster'),('Energiprestanda',r'direktverkande el|oljeuppvärmning')]
 return [(name, ', '.join(sorted(set(re.findall(r'.{0,65}'+pat+r'.{0,90}',text,re.I))))[:400]) for name,pat in rules if re.search(pat,text,re.I)]

st.title('Ålands Fastighetsagent')
st.caption('Fastighetsdata, marknadsöversikt och investeringsanalys • Uppgifter verifieras mot originalannonser')
with st.sidebar:
 st.header('Datakällor')
 st.caption('Automatisk insamling är begränsad till källor som tillåter åtkomst. Ingen källa garanterar full täckning.')
 source=st.selectbox('Källa',['Alla mäklare']+list(SOURCES))
 st.caption('Ytterligare mäklare kan läggas till efter att deras annonsstruktur och hämtningsregler kontrollerats.')
 limit=st.slider('Max detaljsidor per mäklare',1,30,8)
 if st.button('Hämta annonser',type='primary',width='stretch'):
  successes=0;errors=[]
  chosen=SOURCES.items() if source=='Alla mäklare' else [(source,SOURCES[source])]
  for name,index_url in chosen:
   try:
    urls=links_from_index(index_url)
    if not urls:errors.append(f'{name}: inga annonslänkar hittades')
    for u in urls[:limit]:
     try:save(parse_detail(u,name));successes+=1
     except Exception as e:errors.append(f'{name}: {str(e)[:120]}')
   except Exception as e:errors.append(f'{name}: {e}')
  st.success(f'{successes} annonser uppdaterade.')
  if errors:st.warning('Vissa objekt kunde inte hämtas: '+' | '.join(errors[:4]))
 st.divider()
 st.caption('Hyresreferens: ÅSUB, april 2026. Ingen extern AI-tjänst är ansluten i denna version.')

frame=data()
tab1,tab2,tab3,tab4=st.tabs(['Objekt','Marknaden','Investeringsanalys','Prospektgranskning'])
with tab1:
 a,b,c=st.columns([2,1,1]);q=a.text_input('Sök adress eller kommun');typ=b.selectbox('Fastighetstyp',['Alla']+CATEGORIES);municipality=c.selectbox('Kommun',['Alla']+sorted(frame.municipality.dropna().unique().tolist()) if len(frame) else ['Alla'])
 filtered=frame.copy()
 if q:filtered=filtered[filtered.title.str.contains(q,case=False,na=False)|filtered.municipality.str.contains(q,case=False,na=False)]
 if typ!='Alla':filtered=filtered[filtered.category==typ]
 if municipality!='Alla':filtered=filtered[filtered.municipality==municipality]
 st.metric('Registrerade objekt',len(filtered))
 if filtered.empty:st.info('Inga objekt ännu. Prova ”Hämta annonser” i sidomenyn, eller importera CSV nedan.')
 else:
  st.subheader('Fastigheter')
  for r in filtered.head(60).itertuples():
   with st.container(border=True):
    left,right=st.columns([3,1])
    left.markdown(f'**{r.title or "Objekt utan rubrik"}**')
    left.caption(f'{r.municipality or "Okänd kommun"} · {r.category or "Okänd typ"} · {r.source}')
    right.markdown(f'**{r.price:,.0f} €**' if pd.notna(r.price) else '**Pris saknas**')
    right.caption(f'{r.area:g} m²' if pd.notna(r.area) else 'Yta saknas')
    if r.url:st.link_button('Visa hos mäklaren',r.url)
  st.caption('Bilder ingår ännu inte i datainsamlingen. Kontrollera alltid originalannonsen.')
  with st.expander('Jämför alla objekt i tabell'):
   st.dataframe(filtered[['title','municipality','category','price','debtfree','area','fee','source','url']] .rename(columns={'title':'Objekt','municipality':'Kommun','category':'Typ','price':'Pris €','debtfree':'Skuldfritt €','area':'m²','fee':'Vederlag €/mån','source':'Källa','url':'Originalannons'}),hide_index=True,width='stretch',column_config={'Originalannons':st.column_config.LinkColumn('Originalannons')})
 st.subheader('Importera egna objekt')
 upload=st.file_uploader('CSV med kolumner: title, municipality, category, price, debtfree, area, fee, url',type=['csv'])
 if upload and st.button('Importera CSV'):
  try:
   records=pd.read_csv(upload).fillna('')
   for _,r in records.iterrows():
    url=str(r.get('url','')).strip();title=str(r.get('title','')).strip()
    if not title:continue
    item={'id':hashlib.sha256((url or title).encode()).hexdigest()[:20],'title':title,'municipality':str(r.get('municipality','Okänd')),'category':str(r.get('category','Hus/övrigt')),'price':amount(r.get('price','')),'debtfree':amount(r.get('debtfree','')),'area':amount(r.get('area','')),'fee':amount(r.get('fee','')),'url':url,'source':'CSV-import','description':'','updated':datetime.now(timezone.utc).isoformat()}
    save(item)
   st.success('Importerat. Uppdatera sidan för att se objekten.')
  except Exception as e:st.error(str(e))
with tab2:
 st.subheader('Marknadsöversikt')
 if len(frame):
  valid=frame[frame.price.notna() & frame.area.gt(0)].copy()
  valid['Pris/m²']=valid.price/valid.area
  x,y,z=st.columns(3);x.metric('Objekt',len(frame));y.metric('Medianpris',f'{frame.price.median():,.0f} €' if frame.price.notna().any() else 'Saknas');z.metric('Median €/m²',f'{valid["Pris/m²"].median():,.0f} €' if len(valid) else 'Saknas')
  if len(valid):st.plotly_chart(px.bar(valid.groupby('municipality',as_index=False)['Pris/m²'].median(),x='municipality',y='Pris/m²',title='Median annonserat pris per m² efter kommun'),width='stretch')
 else:st.info('Hämta annonser eller importera CSV för att skapa marknadsstatistik.')
 st.caption('Statistiken gäller enbart objekt i den lokala databasen, inte hela Ålands marknad. Annonserade priser är inte försäljningspriser.')
with tab3:
 st.subheader('Investeringsanalys')
 if len(frame):
  options={f'{r.title} · {r.municipality} ({r.source})':r for r in frame.itertuples()}
  selected=options[st.selectbox('Välj fastighet',list(options))]
  price=selected.debtfree if pd.notna(selected.debtfree) else selected.price
  st.write(f'**Försäljningspris:** {selected.price:,.0f} €' if pd.notna(selected.price) else '**Försäljningspris:** Saknas')
  st.write(f'**Skuldfritt pris:** {selected.debtfree:,.0f} €' if pd.notna(selected.debtfree) else '**Skuldfritt pris:** Ej angivet – kontrollera bolagslån')
  st.write(f'**Vederlag:** {selected.fee:,.0f} €/mån' if pd.notna(selected.fee) else '**Vederlag:** Saknas')
  if selected.url:st.link_button('Öppna originalannons',selected.url)
  est=rent_estimate(selected.municipality,selected.area,selected.category)
  if est:st.info(f'ÅSUB-baserad hyresindikator: **{est[0]}–{est[2]} €/mån**, mittpunkt {est[1]} € ({est[3]}). Inte objektspecifik marknadsvärdering.')
  else:st.warning('Ingen bostadshyresindikator för denna fastighetstyp eller saknad boyta.')
  default_price=int(price) if pd.notna(price) else 0
 else:
  selected=None;est=None;default_price=0;st.info('Ingen annons vald – använd kalkylen manuellt.')
 col1,col2=st.columns(2)
 with col1:
  purchase=st.number_input('Totalt skuldfritt anskaffningspris € (exkl. köpkostnader)',min_value=0,value=default_price,step=1000)
  renovation=st.number_input('Renoveringsbudget €',min_value=0,value=0,step=1000)
  transaction=st.number_input('Köpkostnader och avgifter €',min_value=0,value=0,step=500)
  rent=st.number_input('Antagen hyra €/mån',min_value=0,value=est[1] if est else 0,step=25)
 with col2:
  fee=st.number_input('Drift/vederlag €/mån (exklusive amortering)',min_value=0,value=int(selected.fee) if selected is not None and pd.notna(selected.fee) else 0,step=25)
  other=st.number_input('Övriga kostnader €/mån',min_value=0,value=100,step=25)
  vacancy=st.slider('Vakans %',0,30,5)
  equity=st.number_input('Eget kapital €',min_value=0,value=30000,step=1000)
  rate=st.number_input('Låneränta %',min_value=0.0,value=4.0,step=.25)
 loan_type=st.selectbox('Lånetyp', ['Annuitetslån', 'Rak amortering'])
 years=st.number_input('Återbetalningstid (år)',min_value=1,max_value=50,value=25,step=1)

 total=purchase+renovation+transaction
 loan=max(0,total-equity)
 monthly_rate=rate/1200
 months=years*12
 interest=loan*monthly_rate

 if loan==0:
  payment=0.0
  amort=0.0
 elif loan_type=='Annuitetslån':
  if monthly_rate==0:
   payment=loan/months
  else:
   payment=loan*monthly_rate/(1-(1+monthly_rate)**(-months))
  amort=payment-interest
 else:
  amort=loan/months
  payment=interest+amort

 income=rent*(1-vacancy/100)
 monthly_noi=income-fee-other
 noi=monthly_noi*12
 cash_before=monthly_noi-interest
 cash_after=cash_before-amort
 direct_yield=noi/total*100 if total>0 else None
 cash_return=cash_before*12/equity*100 if equity>0 else None

 st.subheader('Resultat per månad')
 st.metric('Lånebelopp',f'{loan:,.0f} €')
 a,b,c=st.columns(3)
 a.metric('Driftnetto/mån',f'{monthly_noi:,.0f} €')
 b.metric('Låneränta/mån',f'{interest:,.0f} €')
 c.metric('Amortering/mån',f'{amort:,.0f} €')
 st.metric('Total lånebetalning/mån',f'{payment:,.0f} €')

 a,b=st.columns(2)
 a.metric('Kassaflöde före amortering och skatt',f'{cash_before:,.0f} €')
 b.metric('Kassaflöde efter amortering, före skatt',f'{cash_after:,.0f} €')

 st.subheader('Avkastning')
 a,b=st.columns(2)
 a.metric('Direktavkastning',f'{direct_yield:.2f} %' if direct_yield is not None else '—')
 b.metric('Avkastning på eget kapital',f'{cash_return:.2f} %' if cash_return is not None else '—')

 st.caption('Avkastning på eget kapital avser kassaflöde före amortering och skatt. Beräkningen använder angivet eget kapital och inkluderar inte värdeförändring.')
 st.caption('Ränta och amortering visas för första månaden. Vid annuitetslån ändras fördelningen över tiden, medan totalbetalningen är konstant vid oförändrad ränta.')


 st.subheader('Högsta inköpspris för önskat kassaflöde')
 target_cash=st.number_input(
  'Önskat kassaflöde efter amortering, före skatt (€/mån)',
  min_value=0,value=200,step=50
 )

 # Högsta tillåtna månatliga lånebetalning
 available_payment=monthly_noi-target_cash
 extra_costs=renovation+transaction

 if available_payment<=0:
  st.warning('Hyresintäkterna efter drift räcker inte till målet, även utan lån.')
 else:
  if loan_type=='Annuitetslån':
   if monthly_rate==0:
    max_loan=available_payment*months
   else:
    max_loan=available_payment*(1-(1+monthly_rate)**(-months))/monthly_rate
  else:
   max_loan=available_payment/(monthly_rate+1/months)

  max_total=equity+max_loan
  max_purchase=max_total-extra_costs

  if max_purchase<0:
   st.warning('Målet kan inte nås med dessa köpkostnader och finansieringsvillkor.')
  else:
   st.metric('Högsta inköpspris',f'{max_purchase:,.0f} €')

   st.subheader('Jämförelse med annonspris')
   asking_price = purchase

   if asking_price > 0:
    price_difference = max(0, asking_price - max_purchase)
    discount = price_difference / asking_price * 100

    a,b,c = st.columns(3)
    a.metric('Annonspris / angivet pris', f'{asking_price:,.0f} €')
    b.metric('Prisskillnad', f'{price_difference:,.0f} €')
    c.metric('Nödvändig rabatt från annonspris', f'{discount:.1f} %')

    if price_difference > 0:
     st.warning(
      f'För att nå ditt kassaflödesmål behöver priset minska '
      f'med cirka {price_difference:,.0f} € ({discount:.1f} %).'
     )
    else:
     st.success('Fastigheten uppfyller kassaflödesmålet vid angivet pris.')
   else:
    st.info('Ange ett inköpspris för att se prisskillnaden.')

   st.caption(
    f'Beräknat med {loan_type.lower()}, {years} års återbetalning, '
    f'{rate:.2f} % ränta och {equity:,.0f} € i eget kapital. '
    'För rak amortering används första månadens betalning.'
   )

 st.caption('Skuldfritt pris används som utgångspunkt när känt. Kontrollera att bolagslånebetalningar inte dubbelräknas. Skatt och framtida större underhåll ingår inte automatiskt.')
with tab4:
 st.subheader('Prospekt och renoveringsrisker')
 pdf=st.file_uploader('Ladda upp prospekt (PDF)',type=['pdf']);description=st.text_area('Eller klistra in mäklarens beskrivning',height=170)
 if pdf:
  try:
   reader=PdfReader(io.BytesIO(pdf.read()));description+='\n'+'\n'.join((p.extract_text() or '') for p in reader.pages[:30])
   st.caption(f'{min(len(reader.pages),30)} sidor genomgångna. Skannade PDF:er utan text kräver OCR.')
  except Exception as e:st.error(f'PDF kunde inte läsas: {e}')
 if description.strip():
  risks=risk_analysis(description)
  if risks:
   for label,excerpt in risks:
    with st.expander('Kontrollpunkt: '+label):st.write(excerpt or 'Nyckelord förekommer – läs originaltexten.')
  else:st.info('Inga definierade riskord hittades. Det innebär inte att objektet är felfritt.')
 st.warning('Detta är en regelbaserad textgranskning, inte en verifierad AI-besiktning. Risker och renoveringskostnader måste kontrolleras av fackperson.')
 st.markdown('[ÅSUB – hyresstatistik 2026](https://www.asub.ax/sv/statistik/hyresstatistik-2026)')
