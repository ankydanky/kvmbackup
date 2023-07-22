#! /usr/bin/env python3
# coding: utf-8

"""
KVMBackup is licensed under GNU General Public License v3.0
Please refer to https://opensource.org/licenses/GPL-3.0 for more information

Originally written by NDK
"""

import os
import sys
import re
import time
import xml.etree.ElementTree as xml
import subprocess
import io

kvm_config = "/etc/libvirt/qemu"
dest_folder = "/data/backup"
max_retries = 4
retry_interval = 30
offmode = "shutdown"
exclude = []


class KVMDomain(object):

    def __init__(self):
        self.xmlfile = None
        self.name = None
        self.disks = []
    
    def setConfigXml(self, xmlfile):
        self.xmlfile = xmlfile
    
    def parse(self):
        xml_data = xml.parse(self.xmlfile)
        root = xml_data.getroot()
        for child in root:
            if child.tag == "name":
                self.name = child.text
            if child.tag == "devices":
                for disk in child.findall("disk"):
                    if disk.attrib['device'] == "disk":
                        sources = disk.findall("source")
                        for src in sources:
                            self.disks.append(src.attrib['file'])
    
    def getStatus(self):
        proc = subprocess.Popen(
            "virsh list --all", shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        proc.wait()
        stdout = proc.communicate()[0]
        for row in stdout.decode().split("\n")[2:-2]:
            cols = re.split("\s{1,}", row)
            if cols[2] == self.name:
                return cols[3]
    
    def isRunning(self):
        if self.getStatus() == "running":
            return True
        return False
    
    def isSuspended(self):
        if self.getStatus() == "paused":
            return True
        return False
    
    def isShutdown(self):
        if self.getStatus() == "shut":
            return True
        return False
    
    def backup(self, disknum):
        filename = self.disks[disknum].split(os.path.sep)[-1]
        try:
            os.unlink(os.path.join(dest_folder, filename))
        except OSError:
            pass
        src_file = open(self.disks[disknum], "rb")
        dest_file = open(os.path.join(dest_folder, filename), "wb")
        total_size = os.stat(self.disks[disknum]).st_size
        transfered = 0
        trans_per_sec = 0
        start_time = int(time.time())
        while True:
            buf_size = io.DEFAULT_BUFFER_SIZE
            data = src_file.read(buf_size)
            if not data:
                break
            dest_file.write(data)
            transfered += buf_size
            seconds = int(time.time()) - start_time
            try:
                trans_per_sec = int((transfered/seconds) / 1024 / 1024)
            except ZeroDivisionError:
                pass
            transfered_mb = int(round(transfered / 1024 / 1024, 0))
            transfer_total = int(round(total_size / 1024 / 1024, 0))
            print(
                f"\t ==> {transfered_mb} / {transfer_total} MB ({seconds} seconds running, overall speed: {trans_per_sec} MB/s)",
                end="\r",
                flush=True
            )
        src_file.close()
        dest_file.close()
        print("", flush=True)
    
    def suspend(self):
        proc = subprocess.Popen(
            f"virsh suspend {self.name}",
            shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        proc.wait()
    
    def resume(self):
        proc = subprocess.Popen(
            f"virsh resume {self.name}",
            shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        proc.wait()
        
    def shutdown(self):
        proc = subprocess.Popen(
            f"virsh shutdown {self.name}", shell=True,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        proc.wait()
    
    def start(self):
        proc = subprocess.Popen(
            f"virsh start {self.name}", shell=True,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        proc.wait()


class KVMBackup(object):
    
    def __init__(self):
        self.domains = []
        self.ignore_shutdown = False
        self.ignore_resume = False
    
    def getDomains(self):
        if "--all" not in sys.argv:
            self.ignore_shutdown = True
            dom = KVMDomain()
            dom.setConfigXml(os.path.join(kvm_config, sys.argv[1]+".xml"))
            dom.parse()
            if dom.isShutdown():
                self.ignore_resume = True
            self.domains.append(dom)
        else:
            for f in os.listdir(kvm_config):
                if not f.lower().endswith(".xml"):
                    continue
                dom = KVMDomain()
                dom.setConfigXml(os.path.join(kvm_config, f))
                dom.parse()
                if dom.name not in exclude:
                    self.domains.append(dom)
    
    def initBackup(self):
        for dom in self.domains:
            abort = False
            print(f"Checking state for {dom.name}... ", end="", flush=True)
            if not dom.isRunning() and not self.ignore_shutdown:
                print("not running.")
                continue
            if offmode == "shutdown":
                print(f"\n\t ==> shutting down. waiting {retry_interval} seconds.")
                dom.shutdown()
                time.sleep(retry_interval)
            else:
                print(f"\n\t ==> suspending. waiting {retry_interval} seconds.")
                dom.suspend()
                time.sleep(retry_interval)
            retry = 0
            if offmode == "shutdown":
                while not dom.isShutdown():
                    print("\t ==> still waiting...")
                    time.sleep(retry_interval)
                    retry += 1
                    if retry == max_retries:
                        abort = True
                        break
            else:
                while not dom.isSuspended():
                    print("\t ==> still waiting...")
                    time.sleep(retry_interval)
                    retry += 1
                    if retry == max_retries:
                        abort = True
                        break
            if abort:
                print("\t ==> taking too long. skipping.")
                continue
            print("\t ==> starting backup...")
            for num in range(len(dom.disks)):
                dom.backup(num)
            if self.ignore_resume:
                continue
            print("\t ==> resuming operation.")
            dom.start() if dom.isShutdown() else dom.resume()
    
    def rollback(self):
        for dom in self.domains:
            dom.start() if dom.isShutdown() else dom.resume()
    
    def run(self):
        self.getDomains()
        self.initBackup()


if __name__ == '__main__':
    app = KVMBackup()
    if (len(sys.argv) == 1 or 
            len(sys.argv) > 2 or
            "--help" in sys.argv or 
            "help" in sys.argv):
        print(f"""
Usage: {sys.argv[0]} [OPTION]
OPTION are:
    DOMAIN      KVM DOMAIN to backup (e.g. Server1, found with 'virsh list')
    --all       find all domains and backup them (running/online ONLY)
    --help      show this message
        """)
        sys.exit(0)
    try:
        app.run()
    except KeyboardInterrupt:
        app.rollback()
