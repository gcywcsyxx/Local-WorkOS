"""Optional UI smoke test: pip install playwright; uses installed Chrome.
Run against an isolated test server; never import personal memory content.
"""
import json
import os
from pathlib import Path
from playwright.sync_api import sync_playwright

URL=os.environ.get('WORKOS_TEST_URL','http://127.0.0.1:18766')
OUT=Path(os.environ.get('WORKOS_TEST_OUTPUT',str(Path.home()/'AppData'/'Local'/'LocalWorkOS-dev'/'browser')))
OUT.mkdir(parents=True,exist_ok=True)

def main():
 with sync_playwright() as p:
  browser=p.chromium.launch(executable_path=r'C:\Program Files\Google\Chrome\Application\chrome.exe',headless=True)
  page=browser.new_page(viewport={'width':1440,'height':1000},device_scale_factor=1)
  errors=[];bad_requests=[]
  page.on('pageerror',lambda error:errors.append(str(error)))
  page.on('response',lambda response:bad_requests.append(str(response.status)+' '+response.url) if response.status>=400 else None)
  page.goto(URL,wait_until='networkidle')
  page.wait_for_selector('[data-page="projects"]')
  page.screenshot(path=str(OUT/'personal.png'),full_page=True)
  result={'initial_h1':page.locator('h1').all_text_contents(),'errors':errors,'bad_requests':bad_requests,'pages':[]}
  for name in ['projects','research','meetings','tasks','memory','finance','deliverables','settings','overview']:
   page.locator('#sidebar [data-page="'+name+'"]',).first.click()
   page.wait_for_timeout(250)
   result['pages'].append({'route':name,'title':page.locator('h1').all_text_contents(),'scroll_width':page.evaluate('document.documentElement.scrollWidth')})
  page.screenshot(path=str(OUT/'overview.png'),full_page=True)
  page.set_viewport_size({'width':390,'height':844})
  page.screenshot(path=str(OUT/'mobile.png'),full_page=True)
  result['mobile_width']=page.evaluate('document.documentElement.scrollWidth')
  result['errors']=errors;result['bad_requests']=bad_requests
  (OUT/'smoke.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
  print(json.dumps(result,ensure_ascii=False,indent=2))
  assert not errors,errors
  assert not bad_requests,bad_requests
  assert result['mobile_width']<=390,'Mobile horizontal overflow'
  browser.close()

if __name__=='__main__':main()
