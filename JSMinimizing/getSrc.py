import re
import requests
from bs4 import BeautifulSoup
import hashlib
import os
import time
# from JSMinimizing.CCJS import *
from JSMinimizing.JSMinifyer import *
import traceback
from Proxy.IPProxy import getIPProxies


class SiteSrcFiles:
    #  Minimize JS Files and then write them over the original JS script
    '''
    html_files:where html cache is stored
    url:site url
    header:user header
    compile_level : see CC
    '''

    def __init__(self, url, header):
        self.url = url
        self.header = header
        self.compile_level = 'SIMPLE_OPTIMIZATIONS'

    def getjsmodified(self):
        try:
            response = requests.get(self.url, self.header)
            if (response.status_code != 200):
                print('Error Occured with return code ' +
                      str(response.status_code))
            else:
                jsfile_counter = 1
                hashed_cache = (hashlib.sha256(bytes(self.url, encoding='utf-8'))).hexdigest()
                sortedHTML = BeautifulSoup(response.text, "html.parser")
                file = open(os.path.abspath('Cache') + '\\' + hashed_cache + 'Uncompressed' + '.html',
                            'w', encoding='utf-8')  # Using SHA256
                file.write(str(sortedHTML))
                file.close()
                jsfile_list1 = sortedHTML.find_all('script',{'type':'text/javascript'})
                jsfile_list2 = sortedHTML.find_all('script',{'type':''})
                jsfile_num = len(jsfile_list1) + len(jsfile_list2)
                print("The Page You Requested Contains {} JavaScript Files".format(jsfile_num))
                for script in jsfile_list1:
                    # create a new script tag with modified script
                    mod_script_tag = sortedHTML.new_tag('script')
                    # add modified script to this new tag (THIS WILL REMOVE <script tpye='text/javascript> TYPE!)
                    compile_start = time.time()
                    compiled_result = manification(script.text, self.compile_level, 'compiled_code') #JS Miniyer
                    mod_script_tag.string = compiled_result
                    script.replace_with(mod_script_tag)
                    # err_check, compiled_result = manification(script.text, self.compile_level, 'compiled_code') #CC
                    compiled_end = time.time()
                    time_cost1 = compiled_end - compile_start
                    print("js_file NO.{} compiling finished, time cost:{}".format(jsfile_counter, time_cost1))
                    jsfile_counter += 1
                for script in jsfile_list2:
                    # create a new script tag with modified script
                    mod_script_tag = sortedHTML.new_tag('script')
                    # add modified script to this new tag (THIS WILL REMOVE <script tpye='text/javascript> TYPE!)
                    compile_start = time.time()
                    compiled_result = manification(script.text, self.compile_level, 'compiled_code')  # JS Miniyer
                    mod_script_tag.string = compiled_result
                    script.replace_with(mod_script_tag)
                    # err_check, compiled_result = manification(script.text, self.compile_level, 'compiled_code') #CC
                    compiled_end = time.time()
                    time_cost2 = compiled_end - compile_start
                    print("js_file NO.{} compiling finished, time cost:{}".format(jsfile_counter, time_cost2))
                    jsfile_counter += 1
                    '''
                    if (err_check):
                        print("JS file No.{} ".format(jsfile_counter) + "Compiling Failed with ERROR CODE:"
                              + str(compiled_result["code"]) + " " + compiled_result["error"])
                        jsfile_counter += 1
                        print("Will Try again with Proxy ON")

                    else:
                        print("JS file No.{} ".format(jsfile_counter) + "Compiling Succeeded!" +
                              "Time Usage:" + str(int(time_cost)) + "s")
                        mod_script_tag.string = compiled_result
                        # Replace the original script with the minimized one
                        script.replace_with(mod_script_tag)
                        jsfile_counter += 1
                    '''
                # file = open(os.path.abspath('JSMinimizing') + '\\jsfile.js', 'w', encoding='utf-8')
                file = open(os.path.abspath('Cache') + '\\' + hashed_cache + '.html',
                            'w', encoding='utf-8')  # Using SHA256
                file.write(str(sortedHTML))
                file.close()
        except Exception as e:
            traceback.print_exc()
