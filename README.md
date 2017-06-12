# kvmbackup
KVMBackup is a python script for backup of KVM domains

The script shuts down the selected or scanned domains, backups them up to a folder and relaunches them.

Usage: kvmbackup.py [OPTION]
OPTION are:
    DOMAIN      KVM DOMAIN to backup (e.g. Server1, found with 'virsh list')
    --all       find all domains and backup them (running/online ONLY)
    --help      show this message

IMPORTANT:
offmode suspend is not working correctly. PLEASE DO NOT USE.
