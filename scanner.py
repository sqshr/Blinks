# Blinks - Burp Headless Scanning Tool [v0.6b (10-Nov-2024)]
# Author: Punit (0xAnuj)
# Linkedin: https://www.linkedin.com/in/0xanuj/
from burp import IBurpExtender, IScannerListener, IHttpListener, IScanIssue, IScanQueueItem
from java.io import BufferedReader, FileReader, File, PrintWriter, FileWriter, InputStreamReader, OutputStream
from java.net import URL, HttpURLConnection, URLDecoder
import datetime
from threading import Thread, Event, Lock,Timer
import time
import re,os
import json
import glob


class BurpExtender(IBurpExtender, IScannerListener, IHttpListener, IScanQueueItem):

    isActiveScanActive = False  
    IDLE_TIMEOUT = 7200
    INACTIVITY_THRESHOLD = 10  
    last_issue_time = datetime.datetime.now() 

    def registerExtenderCallbacks(self, callbacks):
        self._callbacks = callbacks
        self._helpers = callbacks.getHelpers()
        self._scanQueueItems = []
        self._lastRequestTime = datetime.datetime.now()
        self._inactivity_event = Event()
        self._lock = Lock()
        callbacks.setExtensionName("Blinks")
        callbacks.registerScannerListener(self)
        callbacks.registerHttpListener(self)
        self.isActiveScanActive = False
        #self.current_dir = os.path.abspath(os.path.dirname(__file__))
        auto_config_dir = os.path.join("/tmp/blinks_auto_config/*")
        filelist = glob.glob(auto_config_dir)
        print(filelist)
        correct_config_file = max(filelist, key=os.path.getctime)
        print(correct_config_file)
        cfpath = os.path.join(auto_config_dir,correct_config_file)
        print(cfpath)
        #self.log_message("OUTPUT DIRECTORY IS: "+self.output_path)
        self.extConfig = self.load_config(cfpath)
        #self.extConfig = self.load_config("{}/config.json".format(self.current_dir))
        self.output_dir = self.extConfig['OutputPath']
        self.log_file = "{}/logs/scan_status_{}.log".format(self.output_dir,self.extConfig["initialURL"]["host"])
        self.crawled_requests_file = "{}/data/crawled_data_{}_{}.txt".format(self.output_dir,self.extConfig["initialURL"]["host"],datetime.datetime.now().strftime("%Y-%m-%d-%H-%M-%S"))
        self.active_requests_file = "{}/data/active_check_{}_{}.txt".format(self.output_dir,self.extConfig["initialURL"]["host"],datetime.datetime.now().strftime("%Y-%m-%d-%H-%M-%S"))
        self.proxy_requests_file = "{}/data/proxy_data_{}_{}.txt".format(self.output_dir,self.extConfig["initialURL"]["host"],datetime.datetime.now().strftime("%Y-%m-%d-%H-%M-%S"))
        self.report_name = self.extConfig["initialURL"]["host"]
        self.reporttype = self.extConfig["reporttype"]
        self.webhookURL = self.extConfig["webhookurl"]
        self.crawlonly = self.extConfig["crawlonly"]
        self.proxyonly = self.extConfig["proxyonly"]
        self.headers = self.extConfig['headers']
        self.timelimited = self.extConfig['time']
        self.log_message(self.headers)
        self.log_message("Extension Loaded Successfully")
        self.log_message("Blinks v0.5b  Author: Punit")
        self.run_headless_scan()


    def run_headless_scan(self):
        self.log_message("Running Headless Crawl and Audit")
        try:
            iurl = self.extConfig["initialURL"]["url"]
            self.log_message("Targets: " + str(iurl))
            self.log_message("Starting spider for: " + iurl)
            self.scan_url(iurl)
            with open(self.crawled_requests_file, "a") as f:
                f.write("\n===\n")
            with open(self.active_requests_file, "a") as f:
                f.write("\n===\n")
            Thread(target=self.monitor_file_size).start()

        except Exception as e:
            self.log_message("Error running headless crawl and audit: " + str(e), error=True)

    def process_requests(self,input_filename, output_filename):
        try:
            try:
                with open(input_filename, 'r') as file:
                    content = file.read()
                    requests = content.split('===\n')
                    requests = [request.strip() for request in requests if request.strip()]
            except Exception as e:
                self.log_message("Error reading from file: {}. Error: {}".format(input_filename, str(e)))
                return

            seen_requests = set()
            filtered_requests = []

            # Process and filter requests
            for request in requests:
                try:
                    request_lines = request.replace('\r\n', '\n').split('\n')
                    
                    try:
                        method, url, _ = request_lines[0].split()
                    except ValueError as e:
                        self.log_message("Error parsing request line: {}. Error: {}".format(request_lines[0], str(e)))
                        continue

                    try:
                        endpoint = url.split('?')[0]
                        query_string = url.split('?')[1] if '?' in url else ''
                        url_params_keys = set(URLDecoder.decode(query_string, "UTF-8").split('&'))
                        url_params_keys = set(param.split('=')[0] for param in url_params_keys if param)
                    except Exception as e:
                        self.log_message("Error parsing URL: {}. Error: {}".format(url, str(e)))
                        continue

                    body_params_keys = set()

                    if method == 'POST':
                        try:
                            body_start = next((i for i in range(len(request_lines)) if not request_lines[i].strip()), None)
                            if body_start is not None and (body_start + 1) < len(request_lines):
                                body_content = '\n'.join(request_lines[body_start + 1:])

                                headers = {}
                                for line in request_lines[1:body_start]:
                                    if ': ' in line:
                                        key, value = line.split(': ', 1)
                                        headers[key.lower()] = value

                                content_type = headers.get("content-type", "")

                                if "application/x-www-form-urlencoded" in content_type:
                                    body_params_keys = set(URLDecoder.decode(body_content, "UTF-8").split('&'))
                                    body_params_keys = set(param.split('=')[0] for param in body_params_keys if param)
                                elif "application/json" in content_type:
                                    try:
                                        body_params = json.loads(body_content)
                                        body_params_keys = set(body_params.keys())
                                    except ValueError as e:
                                        self.log_message("Invalid JSON in request body: {}. Error: {}".format(body_content[:50], str(e)))
                                elif "multipart/form-data" in content_type:
                                    boundary = content_type.split("boundary=")[1]
                                    body_content = '\n'.join(request_lines[body_start + 1:])
                                    body_content = body_content.replace('\n', '\r\n').encode('utf-8')
                                    multipart_data = BytesParser().parsebytes(body_content, boundary=boundary.encode('utf-8'))

                                    for part in multipart_data.walk():
                                        content_disposition = part.get("Content-Disposition", "")
                                        if "form-data" in content_disposition:
                                            name = content_disposition.split("name=")[1].strip('"')
                                            body_params_keys.add(name)        

                        except Exception as e:
                            self.log_message("Error parsing request body: {}. Error: {}".format(request[:50], str(e)))

                    all_param_keys = url_params_keys.union(body_params_keys)

                    self.log_message("Method: {}, Endpoint: {}, Params: {}".format(method, endpoint, all_param_keys))

                    unique_key = (method, endpoint, frozenset(all_param_keys))

                    if unique_key not in seen_requests:
                        seen_requests.add(unique_key)
                        filtered_requests.append(request)
                    else:
                        self.log_message("Duplicate found: {} {} with params {}".format(method, endpoint, all_param_keys))

                except Exception as e:
                    self.log_message("Error processing request: {}. Error: {}".format(request[:50], str(e)))

            try:
                with open(output_filename, 'w') as file:
                    for request in filtered_requests:
                        try:
                            file.write(request + '\n===\n')
                        except Exception as e:
                            self.log_message("Error writing request to file: {}. Error: {}".format(request[:50], str(e)))
            except Exception as e:
                self.log_message("Error writing to file: {}. Error: {}".format(output_filename, str(e)))

            self.log_message("Filtered requests have been written to {}".format(output_filename))
            self.log_message("Original request count: {}".format(len(requests)))
            self.log_message("Filtered request count: {}".format(len(filtered_requests)))

        except Exception as e:
            self.log_message("Unexpected error in process_requests: {}".format(str(e)))

    def reset_data_files(self):
        if self.isActiveScanActive:
            self.log_message("Inside Reset Files")
            try: 
                with open(self.active_requests_file, "w") as f:
                    f.write("")
                with open(self.crawled_requests_file, "w") as f:
                    f.write("")   
                self.log_message("Done reseting files") 
                self.log_message("EXITING NOW!")
                self._callbacks.exitSuite(False)
            except Exception as e:
                self.log_message(e)

    def start_time_limited_scan(self):
        scan_duration_seconds = int(self.timelimited) * 60
        self.log_message("Starting time-limited scan for {} minutes.".format(self.timelimited))
        Timer(scan_duration_seconds, self.end_scan_due_to_time_limit).start()

    def end_scan_due_to_time_limit(self):
        self.log_message("Time limit reached. Finalizing scan and generating final report.")
        self.report_file = "{}/reports/Final_scan_report_{}_{}.{}".format(
            self.output_dir,
            self.report_name,
            datetime.datetime.now().strftime("%Y-%m-%d-%H-%M-%S"),
            self.reporttype
        )
        self.generate_report(self.reporttype, self.report_file, is_final=True)
        # Exit the Burp Suite
        self._callbacks.exitSuite(False)

    def monitor_file_size(self):
        import os, time
        last_size = -1
        stable_time = None
        self.log_message("Inside Monitor function last size :{} and Stable_time: {} ".format(last_size, stable_time))
        if self.isActiveScanActive:
            file = self.active_requests_file
        else:
            file =self.crawled_requests_file

        while True:
            try:
                current_size = os.path.getsize(file)
                if current_size == last_size:
                    if stable_time is None:
                        stable_time = time.time()  
                    elif time.time() - stable_time > 22:  
                        self.log_message("Crawled Finished!.")
                        self.process_requests(self.crawled_requests_file,self.crawled_requests_file)
                        if self.crawlonly == True:
                            self.log_message("scanning Finished!")
                            self._callbacks.exitSuite(False)
                        else:
                            self.isActiveScanActive = True
                            if self.timelimited > 0:
                                self.start_time_limited_scan()
                            Thread(target=self.monitor_file_size_active).start()
                            Thread(target=self.monitor_idle_time).start()
                            self.log_message(self.isActiveScanActive)
                            self.ActiveScanFileRun(self.isActiveScanActive)
                            break 
                else:
                    stable_time = None  
                last_size = current_size
            except FileNotFoundError:
                self.log_message("Crawled requests file not found.")
            time.sleep(1) 

    def monitor_scan_status(self,scan_queue_item):
          if self.isActiveScanActive:
                try:
                    while True:
                        status = self.scan_queue_item.getStatus()
                        self.log_message("Scan Status: {}".format(status))
                        time.sleep(1)  # Check every 10 seconds
                except Exception as e:
                    self.log_message("ERROR IN MONITOR: {}".format(e))

    def monitor_file_size_active(self):
        import os, time
        last_size = -1
        stable_time = None
        max_wait_time = 300  # 5 minutes max wait

        self.log_message("Active: Inside Monitor function last size: {} and Stable_time: {}".format(last_size, stable_time))
        
        while True:
            if self.isActiveScanActive:
                try:
                    current_size = os.path.getsize(self.active_requests_file)                    
                    if current_size == last_size:
                        if stable_time is None:
                            stable_time = time.time()
                        elif time.time() - stable_time > 120:
                            self.log_message("Active scan completed. Finalizing report.")
                            self.report_file = "{}/reports/Final_scan_report_{}_{}.{}".format(self.output_dir,self.report_name,datetime.datetime.now().strftime("%Y-%m-%d-%H-%M-%S"),self.reporttype)
                            self.generate_report(self.reporttype, self.report_file, is_final=True)
                            self._callbacks.exitSuite(False)
                            break
                        elif time.time() - stable_time > max_wait_time:
                            self.log_message("Exceeded max wait time. Exiting to avoid any freeze.")
                            break
                    else:
                        stable_time = None
                    last_size = current_size

                except FileNotFoundError:
                    self.log_message("Active requests file not found.")
                time.sleep(5)


    def monitor_idle_time(self):
        if self.isActiveScanActive:
            while True:
                current_time = datetime.datetime.now()
                idle_duration = (current_time - self.last_issue_time).total_seconds()

                if idle_duration > self.IDLE_TIMEOUT:
                    self.log_message("No new issues detected for 2 hours. Generating final report and exiting.")
                    self.generate_final_report_and_exit()
                    break

                time.sleep(300)  # Check every 5 minutes


    def generate_report(self, reportType, reportFile, is_final=False):
        try:
            issues = self._callbacks.getScanIssues(None)
            report_suffix = "FINAL" if is_final else "PENDING"
            if is_final:
                report_file_path = "{}/reports/{}_scan_report_{}_{}.{}".format(
                    self.output_dir, report_suffix, self.report_name, datetime.datetime.now().strftime("%Y-%m-%d-%H-%M-%S"), reportType
                )
            else:
                report_file_path = "{}/reports/{}_scan_report_{}.{}".format(
                    self.output_dir, report_suffix, self.report_name, reportType
                )    

            if issues:
                self.log_message("Number of issues found: {}".format(len(issues)))
                file = File(report_file_path)
                self._callbacks.generateScanReport(reportType, issues, file)
                self.log_message("Report saved to {}".format(report_file_path))
                if is_final:
                    self.reset_data_files()
            else:
                self.log_message("No issues found to report.")

        except Exception as e:
            self.log_message("Error saving report: {}".format(str(e)), error=True)

    def generate_final_report_and_exit(self):
        """Generates the final report and exits Burp."""
        self.report_file = "{}/reports/Final_scan_report_{}_{}.{}".format(self.output_dir,self.report_name,datetime.datetime.now().strftime("%Y-%m-%d-%H-%M-%S"),self.reporttype)
        self.generate_report(self.reporttype, self.report_file, is_final=True)
        self._callbacks.exitSuite(False)


    def scan_url(self, url):
        try:
            parsed_url = URL(url)
            self.log_message("Parsed URL: {}".format(parsed_url))
            
            protocol = parsed_url.getProtocol()
            hostname = parsed_url.getHost()
            
            hostname_segments = hostname.split('.')
            
            if len(hostname_segments) == 2:
                # Construct www. subdomain with the same protocol
                www_url = "{}://www.{}".format(protocol, hostname)
                parsed_url = URL(www_url)
                if not self._callbacks.isInScope(parsed_url):
                    self._callbacks.includeInScope(parsed_url)
                    self.log_message("Added www subdomain to scope: {}".format(parsed_url))
            
            if not self._callbacks.isInScope(parsed_url):
                self._callbacks.includeInScope(parsed_url)
                self.log_message("Added URL to scope: {}".format(parsed_url))
            time.sleep(5)
            
            self._callbacks.sendToSpider(parsed_url)
            self._lastRequestTime = datetime.datetime.now()
            self.log_message("Starting spider on {} at {}".format(url, self._lastRequestTime))

        except Exception as e:
            self.log_message("Error scanning URL {}: {}".format(url, str(e)), error=True)


    def processHttpMessage(self, toolFlag, messageIsRequest, messageInfo):
            if self.isActiveScanActive:
                request = self._helpers.bytesToString(messageInfo.getRequest())
                with open(self.active_requests_file, "a") as f:
                    f.write("\n===\n")
                return

            self.log_message("Processing HTTP message: toolFlag={}, messageIsRequest={}".format(toolFlag, messageIsRequest))
            
            if toolFlag == self._callbacks.TOOL_SPIDER or toolFlag == self._callbacks.TOOL_SCANNER:
                if messageIsRequest:
                    requestInfo = self._helpers.analyzeRequest(messageInfo)
                    headers = list(requestInfo.getHeaders())
                    if self.headers:
                        for header in self.headers:
                            headers.append(header)
                    bodyBytes = messageInfo.getRequest()[requestInfo.getBodyOffset():]
                    newRequest = self._helpers.buildHttpMessage(headers, bodyBytes)
                    messageInfo.setRequest(newRequest)

                url = self._helpers.analyzeRequest(messageInfo).getUrl()
                self.log_message("Crawled URL: {}".format(url))
                if self._callbacks.isInScope(url) and not self.is_static_file(url.getPath()):
                    self.save_and_scan_request(messageInfo)
            else:
                self.log_message("Ignoring message with toolFlag: {}, messageIsRequest: {}".format(toolFlag, messageIsRequest))

    def save_and_scan_request(self, messageInfo):
        try:
            request = self._helpers.bytesToString(messageInfo.getRequest())
            with open(self.crawled_requests_file, "a") as f:
                f.write(request + "\n===\n")
        except Exception as e:
            self.log_message("Error saving and scanning request: {}".format(str(e)), error=True)

    def ActiveScanFileRun(self, isActiveScanActive):
        if not isActiveScanActive:
            return
        self.isActiveScanActive = True
        self.log_message("ActiveScanFileRun Active Status: {}".format(self.isActiveScanActive))
        seen_requests = set()
        while True:
            try:
                with open(self.crawled_requests_file, "r") as f:
                    requests = f.read().split("\n===\n")
                    for request in requests:
                        if request.strip() and request not in seen_requests:
                            self.log_message("New request found, sending to scanner")
                            seen_requests.add(request)
                            self.send_to_scanner(request)
                time.sleep(1)
            except Exception as e:
                self.log_message("Error reading crawled requests file: {}".format(str(e)), error=True)

    def send_to_scanner(self, request):
        try:
            host = self.extConfig["initialURL"]["host"]
            port = self.extConfig["initialURL"]["port"]
            protocol = self.extConfig["initialURL"]["protocol"]

            httpService = self._helpers.buildHttpService(host, port, protocol == "https")
            self.log_message("Sending request to scanner")
            self._callbacks.doActiveScan(
                httpService.getHost(),
                httpService.getPort(),
                protocol == "https",
                self._helpers.stringToBytes(request)
            )
        except Exception as e:
            self.log_message("Error sending to scanner: {}".format(str(e)), error=True)


    def log_message(self, message, error=False):
        try:
            with open(self.log_file, "a") as log:
                timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                log.write("[{}] {}{}\n".format(
                    timestamp,
                    "ERROR: " if error else "",
                    message
                ))
                print("[{}] {}{}".format(
                    timestamp,
                    "ERROR: " if error else "",
                    message
                ))
                self._callbacks.printOutput("[{}] {}{}".format(
                    timestamp,
                    "ERROR: " if error else "",
                    message
                ))
        except Exception as e:
            print("Failed to log message: {}".format(str(e)))

    def load_config(self, config_file):
        
        with open(config_file, 'r') as file:
            config = json.load(file)
        return config

    def is_static_file(self, path):
        skip_files = ["/favicon.ico", "/robots.txt"] #need to work on this logic
        if path in skip_files:
            return True
        for ext in self.extConfig.get("staticFileExt", []):
            if path.endswith(".{}".format(ext)):
                return True
        return False
    
    #Ongoing reporting
    def newScanIssue(self, issue):
        self.log_message("New scan issue identified: {}".format(issue.getIssueName()))
        self.last_issue_time = datetime.datetime.now()  # Update last issue time
        self.report_file = "{}/reports/SCAN_PENDING_issues_report_{}.{}".format(self.output_dir, self.report_name, self.reporttype)
        self.generate_report(self.reporttype, self.report_file)

        try:
            issue_details = {
                "issue_name": str(issue.getIssueName().encode('utf-8', errors='ignore').decode('utf-8')),
                "severity": str(issue.getSeverity().encode('utf-8', errors='ignore').decode('utf-8')),
                "confidence": str(issue.getConfidence().encode('utf-8', errors='ignore').decode('utf-8')),
                "url": str(issue.getUrl().toString().encode('utf-8', errors='ignore').decode('utf-8')),
                "issue_detail": issue.getIssueDetail() and str(issue.getIssueDetail().encode('utf-8', errors='ignore').decode('utf-8')),
                "issue_background": issue.getIssueBackground() and str(issue.getIssueBackground().encode('utf-8', errors='ignore').decode('utf-8')),
                "remediation_detail": issue.getRemediationDetail() and str(issue.getRemediationDetail().encode('utf-8', errors='ignore').decode('utf-8')),
                "remediation_background": issue.getRemediationBackground() and str(issue.getRemediationBackground().encode('utf-8', errors='ignore').decode('utf-8'))
            }

            http_messages = issue.getHttpMessages()
            if http_messages and len(http_messages) > 0:
                first_http_message = http_messages[0]
                issue_details["host"] = str(first_http_message.getHttpService().getHost())
                issue_details["port"] = first_http_message.getHttpService().getPort()
                issue_details["protocol"] = "https" if first_http_message.getHttpService().getProtocol() else "http"

                for i, http_message in enumerate(http_messages):
                    request_info = self._helpers.analyzeRequest(http_message)
                    response_info = self._helpers.analyzeResponse(http_message.getResponse())

                    request_headers = [str(header.encode('utf-8', errors='ignore').decode('utf-8')) for header in request_info.getHeaders()]
                    request_body = str(self._helpers.bytesToString(http_message.getRequest())[request_info.getBodyOffset():].encode('utf-8', errors='ignore').decode('utf-8'))
                    
                    response_headers = [str(header.encode('utf-8', errors='ignore').decode('utf-8')) for header in response_info.getHeaders()] if http_message.getResponse() else []
                    response_body = str(self._helpers.bytesToString(http_message.getResponse())[response_info.getBodyOffset():].encode('utf-8', errors='ignore').decode('utf-8')) if http_message.getResponse() else ""

                    issue_details["request_{}_headers".format(i+1)] = request_headers
                    issue_details["request_{}_body".format(i+1)] = request_body
                    issue_details["response_{}_headers".format(i+1)] = response_headers
                    issue_details["response_{}_body".format(i+1)] = response_body
            else:
                self.log_message("No HTTP messages found for issue: {}".format(issue.getIssueName()))

            json_data = json.dumps(issue_details, ensure_ascii=False).encode('utf-8')
            
            self.send_issue_to_webhook(json_data)
            self.report_file = "{}/reports/SCAN_PENDING_issues_report_{}.{}".format(self.output_dir, self.report_name, self.reporttype)
            self.generate_report(self.reporttype, self.report_file)

        except Exception as e:
            self.log_message("ERROR: Error processing issue details: {}".format(str(e)), error=True)


    def send_issue_to_webhook(self, json_data):
        try:
            webhook_url = self.webhookURL 
            if webhook_url == None:
                return
            url = URL(webhook_url)
            conn = url.openConnection()
            conn.setRequestMethod("POST")
            conn.setRequestProperty("Content-Type", "application/json")
            conn.setDoOutput(True)

            output_stream = conn.getOutputStream()
            output_stream.write(json_data.encode('utf-8'))
            output_stream.close()

            response_code = conn.getResponseCode()
            if response_code == HttpURLConnection.HTTP_OK:
                self.log_message("Issue successfully sent to webhook.")
            else:
                self.log_message("Failed to send issue to webhook. Status code: {}".format(response_code), error=True)

            conn.disconnect()

        except Exception as e:
            self.log_message("Error sending issue to webhook: {}".format(str(e)), error=True)



