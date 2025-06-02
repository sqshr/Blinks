import os
import json
import glob
import httpx
import subprocess
import argparse
import time
import shutil

#current_path = os.getcwd()

def get_bapps():
    extensions = []
    userdir = os.path.expanduser("~")
    bappsdir = os.path.abspath(os.path.join(userdir,".BurpSuite","bapps"))

    if not os.path.isdir(bappsdir):
        print("Bapps directory doesn't exist")
        exit(1)

    bappdirlist = os.listdir(bappsdir)

    for bappdir in bappdirlist:
        directory = os.path.join(bappsdir,bappdir)
        manifestfile = "BappManifest.bmf"
        m = open(os.path.join(directory,manifestfile))
        manifest = m.readlines()
        m.close()
        for line in manifest:
            linelist = line.strip().split(":")
            key = linelist[0].strip()
            value=linelist[1].strip()
            match key:
                case "Name":
                    bappname = value
                case "EntryPoint":
                    bappfile = os.path.join(directory,value)
        extension = bappfile.split(".")[-1]

        match extension:
            case "jar":
                bapptype = "java"
            case "py":
                bapptype = "python"
            case "rb":
                bapptype = "ruby"

        extensions.append({"errors":"console","loaded":True,"output":"console","extension_file":bappfile,"name":bappname,"extension_type":bapptype})
    return extensions

def update_burp_config(burpconfig,burp_config_template):
    with open(burpconfig, 'w') as f:
            json.dump(burp_config_template, f, indent=4)    
  
def read_urls(file_path):
    with open(file_path, 'r') as file:
        return [line.strip() for line in file if line.strip()]

def is_url_alive(url):
    if not url.startswith(('http://', 'https://')):
        url = 'http://' + url 
    try:
        response = httpx.get(url, timeout=5, verify=False)
        return response.status_code
    except httpx.RequestError:
        return False

def write_alive_urls(file_path, urls):
    with open(file_path, 'w') as file:
        for url in urls:
            file.write(url + '\n')

def update_blinks_config(config_file_path,config_template):
    with open(config_file_path, 'w') as file:
        json.dump(config_template, file, indent=4)

def update_config(url, webhook, reporttype, crawlonly, config_template):
    parsed_url = httpx.URL(url)
    config_template["initialURL"]["url"] = url
    config_template["initialURL"]["host"] = parsed_url.host
    config_template["initialURL"]["port"] = parsed_url.port or (443 if parsed_url.scheme == "https" else 80)
    config_template["initialURL"]["protocol"] = parsed_url.scheme
    config_template["webhookurl"] = webhook if webhook else None
    if reporttype not in ["HTML", "XML"]:
        raise ValueError("Invalid report type. Only 'HTML' and 'XML' are allowed.")
    config_template["reporttype"] = reporttype
    config_template["crawlonly"] = crawlonly if crawlonly else None
    config_template["OutputPath"] = output_path
    return config_template

def perform_task(url, webhook, reporttype, crawlonly, config_template, config_file_path, current_path, burpconfig):
    config_template = update_config(url, webhook, reporttype, crawlonly, config_template)

    update_blinks_config(config_file_path,config_template)
    
    burp_path = config_template.get("BurpPath")
    project_file = os.path.join(current_path, config_template["initialURL"]["host"])
    print("[+] Running Burp Suite")
    command = f"java -Xmx1G -Djava.awt.headless=true -jar {burp_path} --user-config-file={burpconfig} --unpause-spider-and-scanner"
    try:
        print(f"[+] Scanning {url}. See logs under ./logs")
        process = subprocess.run(command, shell=True, check=True, capture_output=True, text=True)
        #print(process.stdout) 
        #print(process.stderr) 
    except subprocess.CalledProcessError as e:
        print(f"Command '{e.cmd}' returned non-zero exit status {e.returncode}.")
        print(f"Output: {e.output}")
        print(f"Error: {e.stderr}")

def main():
    print('''

    ██████╗ ██╗     ██╗███╗   ██╗██╗  ██╗███████╗
    ██╔══██╗██║     ██║████╗  ██║██║ ██╔╝██╔════╝
    ██████╔╝██║     ██║██╔██╗ ██║█████╔╝ ███████╗
    ██╔══██╗██║     ██║██║╚██╗██║██╔═██╗ ╚════██║
    ██████╔╝███████╗██║██║ ╚████║██║  ██╗███████║
    ╚═════╝ ╚══════╝╚═╝╚═╝  ╚═══╝╚═╝  ╚═╝╚══════╝ v0.6b                           
    BURP HEADLESS SCANNING TOOL     Author: Punit     

    Find reports under ./reports/<Report>.XML       
    
    ''')
    parser = argparse.ArgumentParser(description='BLINKS\n v0.4b Author: Punit(0xAnuj)\n Usage: python external.py -u http://example.com -r HTML -w https:/webhook.com/webhook ')
    parser.add_argument('-u','--url', help='Single URL to process')
    parser.add_argument('-o','--output', help='Directory to store output. By default this is the directory Blinks is stored in.', default=False)
    parser.add_argument('-f','--file', help='File containing URLs to process')
    parser.add_argument('-w','--webhook', default=None, help='Webhook URL (default: NULL)')
    parser.add_argument('-t','--timelimit', default=0, help='Time limited testing [Mins] (default: Limitless)')
    parser.add_argument('-r','--reporttype', required=False, choices=['HTML', 'XML'], help='Report type (HTML or XML). Defaults to XML.',default='XML')
    parser.add_argument('--header', action='append', help='Custom headers/cookies to add to the requests (format: HeaderName:HeaderValue), reuse the argument for multiple headers')
    parser.add_argument('--crawlonly', action='store_true', help='Perfom crawl only scan, it will save all crawled requests under ./data/')
    parser.add_argument('--socks5', action='store_true', help='Use socks5 for VPN at localhost:9090')
    parser.add_argument('--reset', action='store_true', help='Reset all active/crawl data')
    parser.add_argument('--bapps', action='store_true', help='Automatically include all bapps in the scan',default=False)


    args = parser.parse_args()
    current_path = os.path.abspath(os.path.dirname(__file__))
    
    global output_path
    if not args.output:
        output_path = current_path
    else:
        output_path = os.path.abspath(args.output)

    outdirs=['logs','data','reports','burpconfig']
    for d in outdirs:
        dl = os.path.join(output_path,d)
        if not os.path.isdir(dl):
            os.mkdir(dl)

    shutil.copy(os.path.join(current_path,"config.json"),output_path)
    shutil.copy(os.path.join(current_path,"burpconfig","userconfig.json"),os.path.join(output_path,"burpconfig"))
    if output_path != current_path:
        current_path = output_path


    new_target_file_path = os.path.join(current_path, 'new_target.txt')
    config_file_path = os.path.join(current_path, 'config.json')
    burpconfig = os.path.join(current_path,"burpconfig","userconfig.json")
    data_folder  = os.path.join(current_path,"data")
    files = glob.glob(f"{data_folder}/*")
    

    new_extension = {
        "errors": "console",
        "extension_file": os.path.join(current_path, "scanner.py"),
        "extension_type": "python",
        "loaded": True,
        "name": "Headless Crawl and Audit",
        "output": "console"
    }

    with open(config_file_path, 'r') as file:
        config_template = json.load(file)
    print("[+]: Blinks config loaded.")
    jython_jar_path = config_template.get("jythonPath")
    burp_path = config_template.get("BurpPath")
    if not jython_jar_path or not burp_path:
        print("[!]: ERROR: 'jythonPath' or 'BurpPath' is not set in config.json.")
        exit()
    with open(burpconfig, 'r') as file:
        burp_config_template = json.load(file)

    extension_already_present = False

    if 'user_options' in burp_config_template and 'extender' in burp_config_template['user_options']:
        extensions_list = burp_config_template['user_options']['extender'].get('extensions', [])

        for ext in extensions_list:
            if ext.get('extension_file') == new_extension['extension_file'] and ext.get('name') == new_extension['name']:
                extension_already_present = True
                break

        if not extension_already_present:
            extensions_list.append(new_extension)
            burp_config_template['user_options']['extender']['extensions'] = extensions_list
    else:
        burp_config_template['user_options'] = {
            'extender': {
                'extensions': [new_extension]
            }
        }

    if 'python' in burp_config_template['user_options']['extender']:
        burp_config_template['user_options']['extender']['python']['location_of_jython_standalone_jar_file'] = jython_jar_path
    else:
        burp_config_template['user_options']['extender']['python'] = {
            'location_of_jython_standalone_jar_file': jython_jar_path
        }

    if args.bapps:
        extensions = get_bapps()
        burp_config_template['user_options']['extender']['extensions'].extend(extensions)
        print(type(burp_config_template['user_options']['extender']['extensions']))
        print(burp_config_template['user_options']['extender']['extensions'])


    if args.url and args.file:
        parser.error("Specify only one of --url or --file, not both.")
    if not args.url and not args.file:
        parser.error("One of --url or --file must be provided.")

    if args.crawlonly:
        print("[+] Crawl Only Enabled, find crawled requests data under ./data/ ")



    if not extension_already_present:
        update_burp_config(burpconfig,burp_config_template)
        print("Extension added to the Burp configuration.")

    if args.reset:
        if files:
            for file in files:
                try:
                    os.remove(file)
                    print("[!]: Found old data.. deleting please wait")
                    print(f"Deleted: {file}")
                except Exception as e:
                    print(f"[E] Error deleting {file}: {e}")
            print("[+] Old Data have been deleted.\n")
        else:
            print("[+] No Old Data Found")

    if args.timelimit:
        timelimit = args.timelimit
        print(f"[+] Time Limited Testing Initiated for each Active Scan, Time: {timelimit} mins\n")
        config_template["time"] = time
        update_blinks_config(config_file_path,config_template)
    else:
        config_template["time"] = 0
        update_blinks_config(config_file_path,config_template)

    if args.socks5:
        print("[+] Sock5 Enabled, Listening at 127.0.0.1:9090")
        burp_config_template['user_options']['connections']['socks_proxy']['use_proxy'] = True
        update_burp_config(burpconfig,burp_config_template)
    else:
        burp_config_template['user_options']['connections']['socks_proxy']['use_proxy'] = False
        update_burp_config(burpconfig,burp_config_template)

    headers = args.header if args.header else []
    config_template["headers"] = headers
    update_blinks_config(config_file_path,config_template)


    urls = []
    if args.url:
        urls.append(args.url)
    elif args.file:
        urls = read_urls(args.file)

    alive_urls = []
    for url in urls:
        if is_url_alive(url):
            alive_urls.append(url)
        else:
            print(f"[!]: URL is not alive: {url}, Skipping URL!")

    write_alive_urls(new_target_file_path, alive_urls)

    new_urls = read_urls(new_target_file_path)
    for url in new_urls:
        perform_task(url, args.webhook, args.reporttype, args.crawlonly, config_template, config_file_path, current_path, burpconfig)
        print("[+] Halting for 5 seconds")
        time.sleep(5)

if __name__ == '__main__':
    main()
