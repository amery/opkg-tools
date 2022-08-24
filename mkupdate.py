#!/usr/bin/env python2.7
# vim: set ft=python et ts=4 sw=4:

import errno
import fnmatch
import glob
import gzip
import logging
import os
import re
import shutil
import sys

from getopt import getopt

keyValEX   = re.compile(r'^([^: ]+): *(.*)$')
contValEx  = re.compile(r'^ (.*)$')
versionEx  = re.compile(r'^([^:]+): *(.*)$')
dependsEx  = re.compile(r'^ *([^ ]+)')
ipkVerEx   = re.compile(r'^([^:]+:)?([^:].*)$')

def path_join(*args):
    return os.path.normpath(os.path.join(*args))

class Package(object):
    def __init__(self, d):
        self.data = d

    def __str__(self):
        return self.Name

    def __repr__(self):
        return "Package(%s, %s, %s, ...)" % (self.Name, self.Version, self.Architecture)

    def __getitem__(self, key):
        return self.data.get(key, None)

    def __eq__(self, other):
        ret = False
        ill = False

        if isinstance(other, Package) and self.Name == other.Name:
            if self.Version == other.Version:
                ret = True

                for k in [ 'Architecture' ]:
                    if self[k] != other[k]:
                        logging.warning("%s: %s differs (%s vs %s)",
                                self.Name, k, self[k], other[k])
                        ill = True

                for k in [ 'Provides', 'Depends', 'Recommends' ]:
                    # ignore version restrictions
                    #
                    v0 = [ m.group(1) for m in [ dependsEx.match(v) for v in self[k]] if m] if self[k] else []
                    v1 = [ m.group(1) for m in [ dependsEx.match(v) for v in other[k]] if m] if other[k] else []

                    x  = sorted([ v for v in v0 if v not in v1 ])
                    v1 = sorted([ v for v in v1 if v not in v0 ])
                    v0 = x

                    if v0 or v1:
                        logging.warning("%s: %s differs (%r vs %r)",
                                self.Name, k, v0, v1)
                        ill = True

                if ill:
                    logging.warning("%s: ILL (%s)",
                            self.Name,
                            self.Version)

        return ret

    @property
    def Name(self):
        return self.data['Package']

    @property
    def Version(self):
        return self.data['Version']

    @property
    def Architecture(self):
        return self.data['Architecture']

    @property
    def Status(self):
        return self.data.get('Status', "")

    @property
    def Depends(self):
        deps = self.data.get('Depends', [])
        return [ m.group(1) for m in [ dependsEx.match(v) for v in deps] if m ]

    @property
    def Recommends(self):
        deps = self.data.get('Recommends', [])
        return [ m.group(1) for m in [ dependsEx.match(v) for v in deps] if m ]

    @property
    def Ipkfile(self):
        v = ipkVerEx.match(self.Version).group(2)
        f = "%s_%s_%s.ipk" % (self.Name, v, self.Architecture)
        return os.path.join(self.Architecture, f)

def parseManifest(filename):
    logging.info("Parsing %s", filename)

    k, v = None, None
    ret, d = {}, {}

    if fnmatch.fnmatch(filename, '*.gz'):
        f = gzip.GzipFile(filename, 'rt')
    else:
        f = open(filename, 'rt')

    for line in f:
        m = keyValEX.match(line)
        if m:
            k = m.group(1)
            if k == 'Conffiles':
                v = []
            elif k in [ 'Provides', 'Depends', 'Recommends' ]:
                v = sorted(m.group(2).split(', '))
            else:
                v = m.group(2).strip()

            d[k] = v
        elif line == '\n':
            if d:
                p, d = Package(d), {}
                if p.Status.endswith(" not-installed"):
                    logging.info("%s: not-installed - SKIPPING", p.Name)
                else:
                    ret[p.Name] = p
        elif k:
            m = contValEx.match(line)
            if m:
                v = m.group(1).strip()
                if k == 'Conffiles':
                    d[k].append(v.split(' ')[0])
                else:
                    d[k] = ' '.join([d[k], v])
            else:
                logging.warning("%r", line)
        else:
            logging.warning("%r", line)

    if d:
        p = Package(d)
        if p.Status.endswith(" not-installed"):
            logging.info("%s: not-installed - SKIPPING", p.Name)
        else:
            ret[p.Name] = p

    f.close()
    return ret

def DiscoverManifest(ref):
    m, basedir, ipkdir = None, None, None

    if os.path.isfile(ref):
        dirname, filename = os.path.split(ref)

        if filename in [ 'Packages', 'Packages.gz' ]:
            # IPKDIR/Packages.gz
            # IPKDIR/*/Packages.gz
            if os.path.isfile(path_join(dirname, '..', 'Packages.gz')):
                ipkdir = path_join(dirname, '..')
            else:
                ipkdir = dirname

        else:
            m = Manifest(ref)

    elif os.path.isdir(ref):
        # IPKDIR/Packages
        # IPKDIR/Packages.gz
        # IPKDIR/*/Packages.gz
        if os.path.isfile(path_join(ref, 'Packages')) and glob.glob(path_join(ref, '*', 'Packages.gz')):
            ipkdir = ref
        elif os.path.isfile(path_join(ref, '..', 'Packages.gz')):
            ipkdir = path_join(dirname, '..')
        elif os.path.isfile(path_join(ref, 'Packages.gz')):
            ipkdir = ref
        elif os.path.isfile(path_join(ref, 'ipk', 'Packages.gz')):
            ipkdir = path_join(ref, 'ipk')

    if ipkdir:

        if not basedir:
            # ipk/../images/
            p = path_join(ipkdir, '..', 'images')
            if os.path.isdir(p):
                basedir = p

    if m:
        m.basedir = basedir
        m.ipkdir  = ipkdir
    else:
        m = Manifest(None, basedir=basedir, ipkdir=ipkdir)

    return m

class PackageIterator:
    def __init__(self, d):
        self.l = [ (k, p) for k, p in d.iteritems() ]
        self.l.sort(key = lambda t: t[0])
        self.i, self.max = 0, len(self.l)

    def __next__(self):
        if self.i < self.max:
            t = self.l[self.i]
            self.i += 1

            return t[0], t[1]
        else:
            raise StopIteration()

    def next(self):
        return self.__next__()

class Manifest(object):

    def __init__(self, statusFile=None, ipkdir=None, basedir=None, versionFile=None):
        if statusFile:
            self.status = parseManifest(statusFile)
            self.architectures = sorted(list(set(p.Architecture for _, p in self.status.iteritems())))
        else:
            self.status = {}
            self.architectures = None

        self.packages    = None
        self.statusfile  = statusFile
        self.versionfile = versionFile
        self.version = None
        self.basedir = basedir
        self.ipkdir  = ipkdir

    def loadAll(self):
        try:
            self.packages = parseManifest(os.path.join(self.ipkdir, 'Packages.gz'))
        except:
            self.packages = parseManifest(os.path.join(self.ipkdir, 'Packages'))

        if self.architectures:
            for arch in self.architectures:
                p = os.path.join(self.ipkdir, arch, 'Packages.gz')
                self.packages.update(parseManifest(p))
        else:
            archs = []
            for p in glob.glob(os.path.join(self.ipkdir, '*', 'Packages.gz')):
                arch = os.path.basename(os.path.dirname(p))
                if not arch.endswith("-sdk"):
                    archs.append(arch)
                    self.packages.update(parseManifest(p))

            self.architectures = archs

        if self.status:
            outdated = False

            for k, p0 in self.status.iteritems():
                p1 = self.packages.get(k, None)
                if not p1:
                    logging.warning("%s: MISSING", k)
                elif p0 == p1:
                    pass
                else:
                    logging.warning("%s: DIFFERENT THAN IMAGE (%s vs %s)",
                                    k, p0.Version, p1.Version)
                    outdated = True

            if outdated:
                logging.warning("TARGET IMAGE OUT OF DATE")
        else:
            logging.warning("NO TARGET IMAGE")

    def loadVersions(self, filename):
        f = open(filename, 'rt')
        v = {}
        for line in f:
            m = versionEx.match(line)
            if m:
                v[m.group(1)] = m.group(2)
        f.close()

        if 'Product release' in v:
            self.versionfile = filename
            self.versions = v
            self.version  = v['Product release']
            return

    def installedPackages(self):
        return sorted(self.status.keys()) if self.status else []

    def Provides(self, name):
        packages = self.packages if self.packages else self.status
        if name in packages:
            return packages[name]

        for k, p in packages.iteritems():
            if k.endswith("-static"):
                pass
            elif p['Provides'] and name in p['Provides']:
                logging.debug("%s: provided by %s", name, p)
                return p

        return None

    def __getitem__(self, k):
        d = self.packages if self.packages else self.status
        return d.get(k)

    def UpdateFrom(self, goals, base):
        packages = []
        wanted = base.installedPackages() if base else []
        needed = self.installedPackages()
        ok = {}
        again = True

        if base:
            logging.info("Generating update from %s (%s)", base.getVersion(), base.statusfile)
        else:
            logging.info("Generating update from any")

        needed.extend(goals)

        # Packages on the target image
        for k in needed:
            p0 = base[k] if base else None
            p1 = self[k]

            if p1 == None:
                logging.error("%s: MISSING", k)
            elif p0 == None:
                logging.info("%s: NEW (%s)", p1, p1.Version)
                packages.append(p1)
            elif p0 == p1:
                pass
            else:
                logging.info("%s: UPDATED (%s -> %s)",
                        p0, p0.Version, p1.Version)
                packages.append(p1)

            ok[k] = True # don't check again

        # Packages installed on the base
        for k in wanted:
            if k in ok:
                continue
            elif k in self.packages:
                p0 = base[k]
                p1 = self[k]
                if p0 == p1:
                    pass
                else:
                    logging.info("%s: UPDATED (%s -> %s)",
                            p0, p0.Version, p1.Version)
                    logging.debug("%r -> %r", p0, p1)
                    packages.append(p1)

            else:
                logging.warn("%s: GONE", k)

            ok[k] = True # don't check again

        # Add dependencies
        ok = {}
        while again:
            again = False

            for p in packages:
                for k in p.Depends:
                    if self.addDependencies(p, k, ok, packages, base):
                        again = True

                for k in p.Recommends:
                    if self.addDependencies(p, k, ok, packages, base):
                        again = True

        return packages

    def addDependencies(self, p, k, ok, packages, base):
        # checked already?
        if k in ok:
            return False

        p1 = self[k] or self.Provides(k)
        if p1 and p1.Name in ok:
            return False

        # don't check again
        ok[k] = True
        ret = False

        if p1:
            ok[p1.Name] = True

            p0 = base[p1.Name]
            if p0 == None:
                logging.info("%s: NEW (%s)", p1, p1.Version)
                packages.append(p1)
                ret = True
            elif p0 == p1:
                pass
            else:
                logging.info("%s: UPDATED (%s -> %s)",
                        p0, p0.Version, p1.Version)
                packages.append(p1)
                ret = True

        else:
            logging.warn("%s: MISSING DEPENDENCY %s", p, k)

        return ret

    def getVersion(self):
        return self.version or "unknown"

    def __iter__(self):
        d = self.status if self.status else self.packages
        return PackageIterator(d)

def do_update(target, goals, *bases):
    target.loadAll()

    for base in bases:
        packages = target.UpdateFrom(goals, base)
        version  = base.getVersion() if base else "any"
        archs    = base.architectures if base else target.architectures

        if len(packages) > 0:
            packages.sort(key = lambda p: "%s/%s" % (p.Architecture, p.Name))
            outdir = os.path.join(target.basedir, "update-from-" + version, 'ipk')
            logging.info("%u packages required into %s/", len(packages), outdir)

            if os.path.exists(outdir):
                shutil.rmtree(outdir)

            for arch in archs:
                os.makedirs(os.path.join(outdir, arch), 0755)

            def copy(f):
                logging.info(" > %s", f)
                f0 = os.path.join(target.ipkdir, f)
                f1 = os.path.join(outdir, f)
                shutil.copy2(f0, f1)

            try:
                copy('Packages.gz')
            except:
                copy('Packages')

            for arch in archs:
                copy(os.path.join(arch, 'Packages.gz'))

            for p in packages:
                copy(p.Ipkfile)

if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)

    try:
        opts, args = getopt(sys.argv[1:], "x:")
    except getopt.GetoptError:
        print 'mkupdate.py [-x <goal_package>] <target_manifest> <origin_manifest..>'
        sys.exit(2)

    goals = []
    for k, v in opts:
        if k == '-x':
            goals.append(v)

    # parse provided manifests
    manifests = []
    for x in args:
        manifests.append(DiscoverManifest(os.path.normpath(x)))

    if len(manifests) > 1:
        do_update(manifests[0], goals, *manifests[1:])
    elif len(manifests) == 1:
        do_update(manifests[0], goals, None)

