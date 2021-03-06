 #!/usr/bin/python
#coding:utf-8
import re
import sys, urlparse, os
import urllib
import requests, base64
from bs4 import BeautifulSoup
#  try to build a command line version
import argparse
#  colored logging, at present, stderr is used, may shift to log file system
try:
    from termcolor import colored
except:
    def colored(text, color=None, on_color=None, attrs=None):
        return text
def log(s, color=None, on_color=None, attrs=None, new_line=True):
    if not color:
        #  使用 print >> std, str 把输出字符串定义到stderr
        #  new_line: 是否换行
        print ( sys.stderr, str(s) )
    else:
        print ( sys.stderr, colored(str(s), color, on_color, attrs) )

    if new_line:
        print ( sys.stderr.write("\n") )
    sys.stderr.flush()

#  convert relpath to abspath
def absurl(index, relpath=None, normpath=None):
    if normpath is None:
        normpath = lambda x:x
    #  Process for relpath
    if index.lower().startswith('http') or (relpath and relpath.startswith('http')):
        new = urlparse.urlparse(urlparse.urljoin(index, relpath))
        return urlparse.urlunsplit((new.scheme, new.netloc, normpath(new.path), new.query, ''))
    else:
        if relpath:
            return normpath(os.path.join(os.path.dirname(index), relpath))
        else:
            return index

webpage2html_cache = {}
def get(index, relpath=None, verbose=False, usecache=True, verify=True, ignore_error=False, output = False):
    """

    :param index:
    :param relpath: relative path
    :param verbose: use log system?
    :param usecache: use cache?
    :param verify: verify cache?
    :param ignore_error:
    :return: content(str), extra_data(dict, url, content-type e.t.c)
    """
    global webpage2html_cache
    if index.startswith('http') or (relpath and relpath.startswith('http')):
        fullpath = absurl(index, relpath)
        if not fullpath:
            if verbose: log('[WARN] invalid path, %s %s' %(index, relpath), 'yellow')
            return '', None
        # urllib2 only accepts valid url, the following code is taken from urllib
        # http://svn.python.org/view/python/trunk/Lib/urllib.py?r1=71780&r2=71779&pathrev=71780
        #  按照标准， URL 只允许一部分 ASCII 字符（数字字母和部分符号），其他的字符（如汉字）是不符合 URL 标准的。
        #  所以 URL 中使用其他字符就需要进行 URL 编码
        fullpath = urllib.quote(fullpath, safe="%/:=&?~#+!$,;'@()*[]")
        if usecache:
            if fullpath in webpage2html_cache:
                if verbose: log('[CACHE-HIT] -%s' %fullpath)
                return webpage2html_cache[fullpath], None
        headers = {
            'User-Agent': 'Mozilla/5.0 (compatible; MSIE 10.0; Windows NT 6.2; Win64; x64; Trident/6.0)'
        }
        try:
            response = requests.get(fullpath, headers=headers, verify=verify)
            #  Some web page not encoded with UTF-8, which could cause problem
            # TODO need an RE here to find out the encoding


            if verbose: log('[GET] %d -%s' %(response.status_code, response.url))
            if not ignore_error and response.status_code >= 400 or response.status_code < 200:
                content = ''
            else:
                content = response.content
            if usecache:
                #  Save as Cache
                webpage2html_cache[response.url] = response.content
            return content, response.headers
        except Exception as ex:
            if verbose: log('[WARN] Opps - %s %s' %(fullpath, ex), 'yellow')
            return '', None

    elif os.path.exists(index):
        if relpath:
            relpath = relpath.split('#')[0].split('?')[0]
            if os.path.exists(relpath):
                fullpath = relpath
            else:
                #  Normalize a pathname by collapsing redundant separators and up-level references
                #  so that A//B, A/B/, A/./B and A/foo/../B all become A/B.
                fullpath = os.path.normpath(os.path.join(os.path.dirname(index), relpath))
            try:
                ret = open(fullpath, 'rb').read()
                if verbose: log('[LOCAL] found - %s' %fullpath)
                return ret, None
            except IOError as err:
                #  Head up: IOError
                if verbose: log('[WARN] file not found - %s %s'%(index, str(err)), 'yellow')
                return '', None
        else:
            try:
                ret = open(index, 'rb').read()
                if verbose: log('[LOCAL] found - %s' %index)
                return ret, None
            except IOError as err:
                #  Head up: IOError
                if verbose: log('[WARN] file not found - %s %s'%(index, str(err)), 'yellow')
                return '', None
    else:
        if verbose: log('[ERROR] invalid index - %s' %index, 'red')
        return '', None
def get_header_information(index, src, verbose=True):
    sp = urlparse.urlparse(src).path.lower()
    data, extra_data = get(src, src, verbose)
    return extra_data

def save_txt_file(path, list):
    if not os.path.exists(os.path.dirname(os.path.abspath(path))):
        print("The requested path does not exist, will create one...")
        os.mkdir(path)
    with open(path, 'wb') as f:
        for item in list:
            f.writelines(item+'\n')

def analyze(index, verbose=True, comment=True, keep_script=True, prettify=False, full_url=True, verify=False, errorpage=False):
    origin_index = index
    html_doc, extra_data = get(index, verbose = verbose, verify = verify, ignore_error = errorpage)
    if extra_data and extra_data.get('url'):
        index = extra_data['url']
    soup = BeautifulSoup(html_doc, 'lxml')
    soup_title = soup.title.string if soup.title else ''
    css_info_list = []
    js_info_list = []
    image_info_list = []
    # link analyzing
    for link in soup('link'):
        """
        <link href="/index.html" rel="index" />
        <link href="/css/import.css" media="screen, tv, projection" rel="stylesheet" type="text/css" />
        """
        if link.get('href'):

            link_header = get_header_information(index, absurl(index, link['href']), verbose=verbose)
            if link_header is not None:
                try:
                    filetype = link_header.get('content-type')
                except Exception:
                    filetype = ''
                if filetype is None:
                    filetype = ''
                if filetype == 'text/css':
                    css_info_list.append(
                        'name:{} length:{}'.format(link.get('href'), link_header.get('content-length')))
                elif filetype == 'text/script':
                    js_info_list.append('name:{} length:{}'.format(link.get('href'), link_header.get('content-length')))
                elif filetype.startswith('image'):
                    image_info_list.append(
                        'name:{} length:{}'.format(link.get('href'), link_header.get('content-length')))
    """
    save_txt_file('test_js.txt', js_info_list)
    save_txt_file('test_css.txt', css_info_list)
    save_txt_file('test_img.txt', image_info_list)
    """
    for js in soup('script'):

    """
    for img in soup('img'):
        img_src = img.get('src')
        print(img_src)
        if img_src:
            uesless_data, header_info = get(img_src)
            print(header_info)
        #  image_info_list.append(header_info)
    """



    save_txt_file('test_js.txt', js_info_list)
    save_txt_file('test_css.txt', css_info_list)
    save_txt_file('test_img.txt', image_info_list)



"""
    for js in soup('script'):
        print(js)

    for img in soup('img'):
        print(img)
    for tag in soup(True):
        print(tag)
"""
def usage():
    print("""
    usage:
        $ HTMLAnalyzer -u some_url
        $ HTMLAnalyzer -u some_url -o filepath
    options:
        -h, --help 
    examples:
        $ HTMLAnalyzer -h

        $ webpage2html http://www.google.com > google.html
            save google index page for offline reading, keep style untainted
        $ webpage2html -s http://gabrielecirulli.github.io/2048/ > 2048.html
            save dynamic page with Javascript example
            the 2048 game can be played offline after being saved
        $ webpage2html /path/to/xxx.html > xxx_single.html
            combine local saved xxx.html with a directory named xxx_files together into a single html file
    """)














def main():
    parser = argparse.ArgumentParser(description="A web page component analysis tool\n")
    """
    用argparse模块让python脚本接收参数时，对于True/False类型的参数，
    向add_argument方法中加入参数action='store_true'/'store_false'。
    顾名思义，store_true就代表着一旦有这个参数，做出动作“将其值标为True”
    也就是没有时，默认状态下其值为False。反之亦然，store_false也就是默认为True，
    一旦命令中有此参数，其值则变为False。
    """
    parser.add_argument('-o', '--output', action='store_true', help="save result into txt file")
    parser.add_argument('-k', '--insecure', action='store_true', help='ignore the certificate')
    parser.add_argument('-q', '--quiet', action='store_true', help='do not show the log part')
    parser.add_argument('--errorpage', action='store_true', help='save a error page')
    parser.add_argument('-u', '--url', action='store', help='input the original url, followed by the url')
    parser.add_argument('-p', '--path', action='store', help='input the result path')
    #  show intro
    kwargs = {}
    args = parser.parse_args()
    if args.quiet:
        kwargs['verbose'] = False
    if args.errorpage:
        kwargs['errorpage'] = True
    if args.output:
        kwargs['output'] = True
    analyze(args.url)





















if __name__ == "__main__":
    test_url1 = ["https://www.microsoft.com"]
    test_url2 = ["https://www.taobao.com/"]
    test_url3 = ["https://developer.mozilla.org/zh-CN/docs/Web/API/GlobalEventHandlers/onerror"]
    test_url4 = ["http://www.amazarashi.com/top/"]
    test_urls = [
            "https://www.baidu.com",
            "https://www.gooogle.com",
            "https://www.yahoo.co.jp",
            "https://www.imdb.com",
            "https://www.yahoo.com",
            "https://www.twitter.com",
            "https://www.microsoft.com",
            "http://www.softlab.cs.tsukuba.ac.jp/members.html",
            "https://github.com/YagiGo"
        ]
    test_urls2 = [
        "https://www.yahoo.co.jp",
        "https://news.yahoo.co.jp/pickup/6273847",
        "https://news.yahoo.co.jp/pickup/6273853"
        "https://headlines.yahoo.co.jp/hl?a=20180301-00138618-nksports-fight"

    ]
    for url in test_url1:
        analyze(url)


#    main()