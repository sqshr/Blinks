#!/usr/bin/python
import os,json

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
    return json.dumps(extensions)


output = get_bapps()
print(output)
