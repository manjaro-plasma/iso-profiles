#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# === This file is part of Calamares - <http://github.com/calamares> ===
#
#   Copyright 2014 - 2025, Philip Müller <philm@manjaro.org>
#   Copyright 2016, Artoo <artoo@manjaro.org>
#
#   Calamares is free software: you can redistribute it and/or modify
#   it under the terms of the GNU General Public License as published by
#   the Free Software Foundation, either version 3 of the License, or
#   (at your option) any later version.
#
#   Calamares is distributed in the hope that it will be useful,
#   but WITHOUT ANY WARRANTY; without even the implied warranty of
#   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
#   GNU General Public License for more details.
#
#   You should have received a copy of the GNU General Public License
#   along with Calamares. If not, see <http://www.gnu.org/licenses/>.

import libcalamares
import subprocess
import os

from shutil import copy2, copytree
from os.path import join, exists
from libcalamares.utils import target_env_call


class ConfigController:
    def __init__(self):
        self.__root = libcalamares.globalstorage.value("rootMountPoint")
        self.__keyrings = libcalamares.job.configuration.get('keyrings', [])

    @property
    def root(self):
        return self.__root

    @property
    def keyrings(self):
        return self.__keyrings

    def init_keyring(self):
        target_env_call(["pacman-key", "--init"])

    def populate_keyring(self):
        target_env_call(["pacman-key", "--populate"] + self.keyrings)

    def terminate(self, proc):
        target_env_call(['killall', '-9', proc])

    def remove_symlink(self, target):
        for root, dirs, files in os.walk("/" + target):
            for filename in files:
                path = os.path.join(root, filename)
                if os.path.islink(path):
                    os.unlink(path)
            for folder in dirs:
                path = os.path.join(root, folder)
                if os.path.islink(path):
                    os.unlink(path)  

    def copy_file(self, file):
        if exists("/" + file) and self.root != "/":
            copy2("/" + file, join(self.root, file))

    def copy_folder(self, source, target):
        if exists("/" + source):
            copytree("/" + source, join(self.root, target), symlinks=True, ignore_dangling_symlinks=True, dirs_exist_ok=True)

    def remove_pkg(self, pkg, path):
        if exists(join(self.root, path)):
            target_env_call(['pacman', '-R', '--noconfirm', pkg])

    def umount(self, mp):
        subprocess.call(["umount", "-l", join(self.root, mp)])

    def mount(self, mp):
        subprocess.call(["mount", "-B", "/" + mp, join(self.root, mp)])

    def rmdir(self, dir):
        subprocess.call(["rm", "-Rf", join(self.root, dir)])

    def mkdir(self, dir):
        subprocess.call(["mkdir", "-p", join(self.root, dir)])

    def run(self):
        self.init_keyring()
        self.populate_keyring()

        # Generate mirror list
        if exists(join(self.root, "usr/bin/pacman-mirrors")):
            if libcalamares.globalstorage.value("hasInternet"):
                target_env_call(["pacman-mirrors", "-f3"])
        else:
            self.copy_file('etc/pacman.d/mirrorlist')

        # Initialize package manager databases
        if libcalamares.globalstorage.value("hasInternet"):
            target_env_call(["pacman", "-Syy"])

        # Remove symlinks before copying   
        self.remove_symlink('root')

        # Copy skel to root
        self.copy_folder('etc/skel', 'root')

        # Workaround for pacman-key bug
        # FS#45351 https://bugs.archlinux.org/task/45351
        # We have to kill gpg-agent because if it stays
        # around we can't reliably unmount
        # the target partition.
        self.terminate('gpg-agent')
        
        # Workaround for BTRFS amd-ucode.img bug
        # https://gitlab.manjaro.org/release-plan/calamares/-/issues/2
        # We have to copy the amd-ucode.img from the live-session over to target
        self.copy_file('boot/amd-ucode.img')

        # There is a nasty bug in *something*, probably grub and BTRFS, that causes us to be completely
        # unable to boot once the system is installed with a kernel higher than 6.12
        # https://codeberg.org/Calamares/calamares/issues/2440
        # We have to do some nasty dd nonsense to fix it
        # TODO remove me when this is fixed
        if exists(join(self.root, "usr/bin/dd")):
            # Create temporary directory, copy /boot/vmlinuz-* to it, copy back with dd
            target_env_call(["sh", "-c", 'mkdir -p /tmp/vmlinuz-hack && mv /boot/vmlinuz-* /tmp/vmlinuz-hack/ && find /tmp/vmlinuz-hack/ -maxdepth 1 -type f -exec sh -c \'dd if="$1" of="/boot/$(basename "$1")"\' sh {} \;'])

        # Enable KDE Initial System Setup when available
        if exists(join(self.root, "usr/lib/libexec/kde-initial-system-setup-bootutil")):
            target_env_call(["systemd-sysusers"])
            target_env_call(["systemctl", "enable", "kde-initial-system-setup.service"])
            target_env_call(["ln", "-sfv", "/usr/share/zoneinfo/Etc/UTC", "/etc/localtime"])

        # Enable 'menu_auto_hide' when supported in grubenv
        if exists(join(self.root, "usr/bin/grub-set-bootflag")):
            target_env_call(["grub-editenv", "-", "set", "menu_auto_hide=1", "boot_success=1"])

        # Install Office Suite if selected (WIP)
        office_package = libcalamares.globalstorage.value("packagechooser_packagechooser")
        if not office_package:
            libcalamares.utils.warning("no office suite selected, {!s}".format(office_package))
        else:
            # For PoC we added the Office Packages to mhwd-live overlay in 18.1.0
            cmd = ["pacman", "-S", office_package, "--noconfirm", "--config", "/opt/mhwd/pacman-mhwd.conf" ]
            self.mkdir("opt/mhwd")
            self.mount("opt/mhwd")
            self.mount("etc/resolv.conf")
            target_env_call(cmd)
            self.umount("opt/mhwd")
            self.rmdir("opt/mhwd")
            self.umount("etc/resolv.conf")

        # Remove calamares
        self.remove_pkg("calamares", "usr/bin/calamares")
        self.remove_pkg("calamares-git", "usr/bin/calamares")

        # Make sure root folder is set to 750
        root_home = join(self.root, "root")
        existing_root_mode = os.stat(root_home).st_mode & 0o755
        if existing_root_mode == 0o755:
                try:
                    os.chmod(root_home, 0o750)  # Want /root to be rwxr-x---
                except OSError as e:
                    libcalamares.utils.warning("Could not set /root to safe permissions: {}".format(e))
                    # But ignore it
                    pass

        return None


def run():
    """ Misc postinstall configurations """

    config = ConfigController()

    return config.run()
