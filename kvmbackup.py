#! /usr/bin/env python
# coding: utf-8

from __future__ import unicode_literals, print_function

import os
import sys
import re
import time
import xml.etree.ElementTree as xml
import subprocess

kvm_config = "/etc/libvirt/qemu"
dest_folder = "/mnt/backup"
max_retries = 5
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
        for row in stdout.split("\n")[2:-2]:
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
        dest_file = open(os.path.join(dest_folder, filename), "ab")
        total_size = os.stat(self.disks[disknum]).st_size
        transfered = 0
        trans_per_sec = 0
        start_time = int(time.time())
        while True:
            buf = 8192
            data = src_file.read(buf)
            if not data:
                break
            dest_file.write(data)
            transfered += buf
            seconds = int(time.time()) - start_time
            try:
                trans_per_sec = int((transfered/seconds) / 1024 / 1024)
            except ZeroDivisionError:
                pass
            sys.stdout.write(
                "\r\t ==> %s / %s MB (%s seconds running, overall speed: %s MB/s)" % (
                    transfered/1024/1024, total_size/1024/1024, seconds, trans_per_sec
                )
            )
            sys.stdout.flush()
        src_file.close()
        dest_file.close()
    
    def suspend(self):
        proc = subprocess.Popen(
            "virsh suspend %s" % self.name,
            shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        proc.wait()
    
    def resume(self):
        proc = subprocess.Popen(
            "virsh resume %s" % self.name,
            shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        proc.wait()
        
    def shutdown(self):
        proc = subprocess.Popen(
            "virsh shutdown %s" % self.name, shell=True,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        proc.wait()
    
    def start(self):
        proc = subprocess.Popen(
            "virsh start %s" % self.name, shell=True,
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
            sys.stdout.write("Checking state for %s... " % dom.name)
            sys.stdout.flush()
            if not dom.isRunning() and not self.ignore_shutdown:
                sys.stdout.write("not running.\n")
                sys.stdout.flush()
                continue
            if offmode == "shutdown":
                sys.stdout.write("\n\t ==> shutting down. waiting 60 seconds.\n")
                sys.stdout.flush()
                dom.shutdown()
                time.sleep(60)
            else:
                sys.stdout.write("\n\t ==> suspending. waiting 60 seconds.\n")
                sys.stdout.flush()
                dom.suspend()
                time.sleep(60)
            retry = 0
            if offmode == "shutdown":
                while not dom.isShutdown():
                    sys.stdout.write("\t ==> still waiting...\n")
                    sys.stdout.flush()
                    time.sleep(60)
                    retry += 1
                    if retry == max_retries:
                        abort = True
                        break
            else:
                while not dom.isSuspended():
                    sys.stdout.write("\t ==> still waiting...\n")
                    sys.stdout.flush()
                    time.sleep(60)
                    retry += 1
                    if retry == max_retries:
                        abort = True
                        break
            if abort:
                sys.stdout.write("\t ==> taking too long. skipping.\n")
                sys.stdout.flush()
                continue
            sys.stdout.write("\t ==> starting backup... \n")
            sys.stdout.flush()
            for num in xrange(len(dom.disks)):
                dom.backup(num)
            sys.stdout.write(" done.\n")
            if self.ignore_resume:
                continue
            sys.stdout.write("\t ==> resuming operation.\n")
            sys.stdout.flush()
            if dom.isShutdown():
                dom.start()
            else:
                dom.resume()
    
    def rollback(self):
        for dom in self.domains:
            if dom.isShutdown():
                dom.start()
            else:
                dom.resume()
    
    def run(self):
        self.getDomains()
        self.initBackup()


if __name__ == '__main__':
    app = KVMBackup()
    if (len(sys.argv) == 1 or 
            len(sys.argv) > 2 or
            "--help" in sys.argv or 
            "help" in sys.argv):
        print("""
Usage: %s [OPTION]
OPTION are:
    DOMAIN      KVM DOMAIN to backup (e.g. Server1, found with 'virsh list')
    --all       find all domains and backup them (running/online ONLY)
    --help      show this message
        """ % sys.argv[0])
        sys.exit(0)
    try:
        app.run()
    except KeyboardInterrupt:
        app.rollback()
