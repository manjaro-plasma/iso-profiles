#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# === This file is part of Calamares - <http://github.com/calamares> ===
#
#   Copyright 2017-2025, Philip Müller <philm@manjaro.org>
#   SHAcrypt code copyright © 2024 Tony Garnock-Jones
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
import os
import logging
import hashlib
import secrets
from shutil import copy2, copytree
from os.path import join, exists
from libcalamares.utils import target_env_call


class ConfigOem:
    def __init__(self):
        self.__root = libcalamares.globalstorage.value("rootMountPoint")
        self.__groups = 'video,audio,power,disk,storage,optical,network,lp,scanner,wheel,autologin'

    @property
    def root(self):
        return self.__root

    @property
    def groups(self):
        return self.__groups

    @staticmethod
    def change_user_password(user, new_password):
        """ Changes the user's password """
        try:
            # shadow_password = crypt.crypt(new_password, crypt.mksalt(crypt.METHOD_SHA512))
            shadow_password = shacrypt(new_password.encode('utf-8'))
        except:
            logging.warning(_("Error creating password hash for user {0}".format(user)))
            return False

        try:
            target_env_call(['usermod', '-p', shadow_password, user])
        except:
            logging.warning(_("Error changing password for user {0}".format(user)))
            return False

        return True

    @staticmethod
    def remove_symlink(target):
        for root, dirs, files in os.walk("/" + target):
            for filename in files:
                path = os.path.join(root, filename)
                if os.path.islink(path):
                    os.unlink(path)

    def copy_file(self, file):
        if exists("/" + file):
            copy2("/" + file, join(self.root, file))

    def copy_folder(self, source, target):
        if exists("/" + source):
            copytree("/" + source, join(self.root, target), symlinks=True, ignore_dangling_symlinks=True,
                     dirs_exist_ok=True)

    def run(self):
        target_env_call(['groupadd', 'autologin'])
        target_env_call(['useradd', '-m', '-s', '/bin/bash', '-U', '-G', self.groups, 'gamer'])
        self.change_user_password('gamer', 'gamer')
        path = os.path.join(self.root, "etc/sudoers.d/g_gamer")
        with open(path, "w") as oem_file:
            oem_file.write("gamer ALL=(ALL) NOPASSWD: ALL")

        # Remove symlinks before copying   
        self.remove_symlink('root')

        # Copy skel to root
        self.copy_folder('etc/skel', 'root')

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

        # Enable 'menu_auto_hide' when supported in grubenv
        if exists(join(self.root, "usr/bin/grub-set-bootflag")):
            target_env_call(["grub-editenv", "-", "set", "menu_auto_hide=1", "boot_success=1"])

        return None


# ------------ BEGIN Copyright © 2024 Tony Garnock-Jones. ------------------
# SHAcrypt using SHA-512, after https://akkadia.org/drepper/SHA-crypt.txt.
#
# Copyright © 2024 Tony Garnock-Jones.
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

alphabet = \
    [ord(c) for c in './0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz']
permutation = [
    [0, 21, 42], [22, 43, 1], [44, 2, 23], [3, 24, 45],
    [25, 46, 4], [47, 5, 26], [6, 27, 48], [28, 49, 7],
    [50, 8, 29], [9, 30, 51], [31, 52, 10], [53, 11, 32],
    [12, 33, 54], [34, 55, 13], [56, 14, 35], [15, 36, 57],
    [37, 58, 16], [59, 17, 38], [18, 39, 60], [40, 61, 19],
    [62, 20, 41], [-1, -1, 63],
]


def encode(bs64):
    result = bytearray(4 * len(permutation))
    i = 0
    for group in permutation:
        g = lambda j: bs64[j] if j != -1 else 0
        bits = g(group[0]) << 16 | g(group[1]) << 8 | g(group[2])
        result[i] = alphabet[bits & 63]
        result[i + 1] = alphabet[(bits >> 6) & 63]
        result[i + 2] = alphabet[(bits >> 12) & 63]
        result[i + 3] = alphabet[(bits >> 18) & 63]
        i = i + 4
    return bytes(result).decode('ascii')[:-2]


def repeats_of(n, bs):
    return bs * int(n / len(bs)) + bs[:n % len(bs)]


def digest(bs):
    return hashlib.sha512(bs).digest()


def shacrypt(password, salt=None, rounds=5000):
    if salt is None:
        salt = encode(secrets.token_bytes(64))[:16].encode('ascii')
    salt = salt[:16]

    B = digest(password + salt + password)
    Ainput = password + salt + repeats_of(len(password), B)
    v = len(password)
    while v > 0:
        Ainput = Ainput + (B if v & 1 else password)
        v = v >> 1
    A = digest(Ainput)

    DP = digest(password * len(password))
    P = repeats_of(len(password), DP)
    DS = digest(salt * (16 + A[0]))
    S = repeats_of(len(salt), DS)

    C = A
    for round in range(rounds):
        Cinput = b''
        Cinput = Cinput + (P if round & 1 else C)
        if round % 3: Cinput = Cinput + S
        if round % 7: Cinput = Cinput + P
        Cinput = Cinput + (C if round & 1 else P)
        C = digest(Cinput)

    if rounds == 5000:
        return '$6$' + salt.decode('ascii') + '$' + encode(C)
    else:
        return '$6$rounds=' + str(rounds) + '$' + salt.decode('ascii') + '$' + encode(C)
# ------------ END Copyright © 2024 Tony Garnock-Jones. ------------------


def run():
    """ Set OEM User """

    oem = ConfigOem()

    return oem.run()
