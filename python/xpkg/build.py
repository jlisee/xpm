# Author: Joseph Lisee <jlisee@gmail.com>

# Python Imports
import hashlib
import os
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile

# Project Imports
from xpkg import linux
from xpkg import paths
from xpkg import util


# Not really sure this fits here, but it's the only module that uses it
def fetch_file(filehash, url):
    """
    Download the desired URL with the given hash
    """

    # Make sure cache exists
    cache_dir = os.path.expanduser(os.path.join('~', '.xpkg', 'cache'))

    if not os.path.exists(cache_dir):
        os.makedirs(cache_dir)

    # Get the path where the file will be placed in our cache
    cache_path = os.path.join(cache_dir, filehash)

    # See if we need to download the file
    download_file = not os.path.exists(cache_path)

    if os.path.exists(cache_path):
        # Lets verify the hash of the existing file, it's mostly ok to do this
        # because we need to read the file off disk to unpack it and the OS will
        # cache it.

        # Get the hash types
        valid_types = set(['md5', 'sha1', 'sha224', 'sha256', 'sha384',
                           'sha512'])

        # Get the information we need to do the hashing
        hash_typename, hex_hash = filehash.split('-')

        hash_type = getattr(hashlib, hash_typename)

        current_hash = util.hash_file(open(cache_path),
                                      hash_type=hash_type)

        # Check if the hashes don't match and if they don't make sure we can the
        # file
        if current_hash != hex_hash:
            download_file = True

    else:
        download_file = True

    # Download if needed
    if download_file:
        p = util.fetch_url(url, cache_path)
        print url,p

    return cache_path


class Toolset(object):
    """
    A set of build dependencies that lets you build your desired software.

    TODO: use a versioned serialization system for this
    """

    REPLACE_VAR = 1
    APPEND_VAR = 2
    PREPEND_VAR = 3

    def __init__(self, name, pkg_info, env_vars = None):
        self.name = name
        self.build_deps = pkg_info

        if env_vars is None:
            self.env_vars = {}
        else:
            self.env_vars = env_vars


    def to_dict(self):
        """
        Serialize this toolset to a dict.
        """
        return {
            'name' : self.name,
            'build-deps' : self.build_deps,
            'env-vars' : self.env_vars
        }


    def lookup_build_dep(self, depname):
        """
        Translates the given dependency to the specific one based on the
        provided build_deps.  If string of 0 length is returned the dependency
        should be ignored.
        """

        # Error out if we don't have the require dep
        if not depname in self.build_deps:
            args = (self.name, depname)
            msg = 'Toolset "%s" does not have a package for: "%s"' % args
            raise Exception(msg)

        # Return the desired dep!
        return self.build_deps[depname]


    def get_env_var_info(self, subs):
        """
        Returns the information about what environment variables that people are
        settings.
        """

        actions_table = {
            self.REPLACE_VAR : 'replace',
            self.APPEND_VAR : 'append',
            self.PREPEND_VAR : 'prepend',
        }

        vars_by_action = {}

        for varname, inputs in self.env_vars.iteritems():
            raw_value, method = inputs

            value = raw_value % subs
            action = actions_table[method]

            vars_by_action.setdefault(action, {})[varname] = value

        return vars_by_action


    def apply_env_vars(self, subs):
        """
        Apply the configured environment vars to our current environment
        """

        for varname, inputs in self.env_vars.iteritems():
            raw_value, method = inputs

            # Sub the value
            value = raw_value % subs

            # Set value based on replacement rule
            if method == self.REPLACE_VAR:
                new_value = value
            elif method == self.APPEND_VAR:
                new_value = os.environ.get(varname, '') + value
            elif method == PREPEND_VAR:
                new_value = value + os.environ.get(varname, '')
            else:
                raise Exception('Invalid method!')

            os.environ[varname] = new_value


    @staticmethod
    def create_from_dict(d):
        """
        Create the toolset from the serialized dict.
        """
        return Toolset(name=d['name'],
                       pkg_info=d['build-deps'],
                       env_vars=d['env-vars'])


    @staticmethod
    def lookup_by_name(name):
        """
        Grab a built in toolset by name.
        """

        if not (name in BuiltInToolsets):
            raise Exception("Can't find toolset '%s'" % name)

        return BuiltInToolsets[name]


class LocalToolset(Toolset):
    """
    Resolve all build deps to '', so that we use whatever the system has.
    """

    def __init__(self):
        # TODO: only add this path on linux
        env_vars = {'LDFLAGS' : LD_VAR}

        Toolset.__init__(self, 'local', pkg_info={}, env_vars=env_vars)


    def lookup_build_dep(self):
        return ''


# Sets up dynamic linker to point to our indirection path
LD_VAR = (' -Wl,--dynamic-linker=%(LD_SO_PATH)s', Toolset.APPEND_VAR)

# Default GNU toolset
GNUToolset = Toolset(
    'GNU',
    pkg_info={
        'shell' : 'dash',
        'base' : 'coreutils',
        'linker' : 'binutils',
        'c-compiler' : 'gcc',
        'c++-compiler' : 'gcc',
        'libc' : 'libc',
    },
    env_vars={
        'CC' : ('gcc', Toolset.REPLACE_VAR),
        'CXX' : ('g++', Toolset.REPLACE_VAR),
        'LDFLAGS' : LD_VAR,
    })

# Toolset for testing
TestToolset = Toolset(
    'Test',
    pkg_info = {
        'shell' : 'busybox',
        'base' : 'busybox',
        'linker' : 'tcc',
        'c-compiler' : 'tcc',
        'libc' : 'uclibc',
    },
    env_vars = {
        'CC' : ('tcc', Toolset.REPLACE_VAR),
        'LD_SO' : ('%(LD_SO_PATH)s', Toolset.REPLACE_VAR),
    })

# Our map of toolsets
BuiltInToolsets = {
    'GNU' : GNUToolset,
    'local' : LocalToolset(),
    'Test' : TestToolset,
}

DefaultToolsetName = 'local'


class PackageBuilder(object):
    """
    Assuming all the dependency conditions for the XPD are met, this builds
    and install the a package based on it's XPD into the target directory.
    """

    def __init__(self, package_xpd):
        self._xpd = package_xpd
        self._work_dir = None
        self._target_dir = None
        self._output = None


    def build(self, target_dir, environment = None, output_to_file=True):
        """
        Right now this just executes instructions inside the XPD, but in the
        future we can make this a little smarter.

        It returns the info structure for the created package.  See the XPA
        class for the structure of the data returned.
        """

        # Create our temporary directory
        self._work_dir = tempfile.mkdtemp(suffix = '-xpkg-' + self._xpd.name)

        # TODO: LOG THIS
        print 'Working in:',self._work_dir

        # Create our output
        if output_to_file:
            # Form a hopefully unique name for the output file
            args = (self._xpd.name, self._xpd.version)
            output_file = '%s-%s_build.log' % args

            # Put the file in our environment if we have, or the current
            # directory
            if environment:
                # Find out log dir
                log_dir = environment.log_dir(environment.root)

                # Make sure it exists
                util.ensure_dir(log_dir)

                # Now finally commit to our path
                output_path = os.path.join(log_dir, output_file)
            else:
                output_path = os.path.abspath(os.path.join('.', output_file))

            # TODO: LOG THIS
            print 'Log file:',output_path

            # Open our file for writing
            self._output = open(output_path, 'w')
        else:
            self._output = None

        # Store our target dir
        self._target_dir = target_dir
        util.ensure_dir(self._target_dir)

        # Determine our environment directory
        if environment:
            self._env_dir = environment._env_dir
        else:
            self._env_dir = ''

        # Setup the ld.so symlink in the target dir pointing to either
        # the system ld.so, or the current environments
        ld_target_dir = self._target_dir
        update_root = self._env_dir if len(self._env_dir) else self._target_dir

        linux.update_ld_so_symlink(update_root, ld_target_dir)

        try:
            # Store the current environment
            env_vars = util.EnvStorage(store = True)

            # If we have an environment apply it's variables so the build can
            # reference the libraries installed in it
            if environment:
                environment.apply_env_variables()

            # Fetches and unpacks all the required sources for the package
            self._get_sources()

            # Determine what directory we have to do the build in
            dirs = [d for d in os.listdir(self._work_dir) if
                    os.path.isdir(os.path.join(self._work_dir, d))]

            if 'build-dir' in self._xpd._data:
                # If the user specifies a build directory use it
                rel_build_dir = self._xpd._data['build-dir']
                build_dir = os.path.join(self._work_dir, rel_build_dir)

                # Make sure the directory exists
                util.ensure_dir(build_dir)
            elif len(dirs) == 1:
                build_dir = os.path.join(self._work_dir, dirs[0])
            else:
                build_dir = self._work_dir

            with util.cd(build_dir):
                # Standard build configure install
                self._configure()

                self._build()

                new_paths = self._install()
        finally:
            # Put back our environment
            env_vars.restore()

            self._env_dir = ''

            # Close our output file if it exists
            if self._output:
                self._output.close()
                self._output = None

            # Make sure we cleanup after we are done
            shutil.rmtree(self._work_dir)


        return self._create_info(new_paths)


    def _get_sources(self):
        """
        Fetches and unpacks all the needed source files.
        """

        # Download and unpack our files
        for filehash, info in self._xpd._data['files'].iteritems():

            # Translate the URL as needed, this is so we can address files
            # (like patches) in the tree
            base_url = info['url']

            if base_url.startswith('xpd://'):
                # Pull out the relative file path from our URL
                rel_path = base_url[len('xpd://'):]

                # Get the directory of our XPD
                xpd_dir, _ = os.path.split(self._xpd.path)

                # Build the path to the file relative to that dir
                file_path = os.path.join(xpd_dir, rel_path)

                # Build the final absolute path
                final_url = 'file://' + os.path.abspath(file_path)
            else:
                final_url = base_url

            # Fetch our file
            download_path = fetch_file(filehash, final_url)

            # Unpack or copy file
            end_match = [final_url.endswith(e) for e in
                         ('.tar.gz', 'tar.bz2', '.tar.xz')]
            is_tar = reduce(lambda x,y: x | y, end_match)

            if is_tar:
                # Unpack into the working directory
                root_dir = util.unpack_tarball(download_path, self._work_dir)
            else:
                # Copy the file into the working dir
                _, file_name = os.path.split(final_url)

                dest_path = os.path.join(self._work_dir, file_name)

                shutil.copyfile(download_path, dest_path)

            # Move if needed
            relative_path = info.get('location', None)

            if relative_path:
                dst_path = os.path.join(self._work_dir, relative_path)

                # TODO: LOG THIS
                print root_dir,'->',dst_path

                shutil.move(root_dir, dst_path)


    def _configure(self):
        """
        Run a configure step for the package if it has one.
        """

        # Configure if needed
        if 'configure' in self._xpd._data:
            # TODO: log this
            print 'Configuring...'
            self._run_cmds(self._xpd._data['configure'])


    def _build(self):
        """
        Builds the desired package.
        """

        # TODO: log this
        print 'Building...'
        self._run_cmds(self._xpd._data['build'])


    def _install(self):
        """
        Installs the package, keeping track of what files it creates.
        """

        # TODO: log this
        print 'Installing...'

        pre_paths = set(util.list_files(self._target_dir))

        self._run_cmds(self._xpd._data['install'])

        post_paths = set(util.list_files(self._target_dir))

        new_paths = post_paths - pre_paths

        return new_paths


    def _run_cmds(self, raw):
        """
        Runs either a single or list of commands, subbing in all variables as
        needed for each command.
        """

        # If don't have a list of cmds make a single cmd list
        if isinstance(raw, list):
            cmds = raw
        else:
            cmds = [raw]

        # Run each command in turn
        for raw_cmd in cmds:
            # Make sure we have env_root when needed
            if raw_cmd.count('%(env_root)s') and len(self._env_dir) == 0:
                raise Exception('Package references environment root, '
                                'must be built in an environment')

            # Sub in our variables into the commands
            cmd = raw_cmd % {
                'jobs' : str(util.cpu_count()),
                'prefix' : self._target_dir,
                'arch' : platform.machine(),
                'env_root' : self._env_dir,
            }

            # Run our command
            self._shellcmd(cmd, self._output)


    def _shellcmd(self, cmd, output=None):
        """
        Runs the given shell command, either output to stderr/stdout or
        the given file object.

        It will throw a CallProcessError if the process fails.
        """

        # Determine where our output goes
        if output:
            stdout = output
            stderr = output
        else:
            stdout = sys.stdout
            stderr = sys.stderr

        # Describe our command
        stdout.write('[cmd] {0}\n'.format(cmd))

        # Flush everything before running our process so that we make sure our
        # command appears in the proper ordering
        stdout.flush()
        stderr.flush()

        # Now lets get writing
        subprocess.check_call(cmd, stderr=stderr, stdout=stdout, shell=True)



    def _create_info(self, new_paths):
        """
        Creates the info structure from the new files and the package XPD info.
        """

        # Split paths by files and directories
        new_dirs = set()
        new_files = set()

        for path in new_paths:
            if os.path.isdir(os.path.join(self._target_dir, path)):
                new_dirs.add(path)
            else:
                new_files.add(path)

        # Find all instances of our install path in our data
        install_path_offsets = self._find_path_offsets(new_files)

        if len(self._xpd.packages()) == 1:
            # Single package path
            infos = [{
                'name' : self._xpd.name,
                'version' : self._xpd.version,
                'description' : self._xpd.description,
                'dependencies' : self._xpd.dependencies,
                'dirs' : list(new_dirs),
                'files' : list(new_files),
                'install_path_offsets' : install_path_offsets,
            }]
        else:
            # Find the catch all package if there is one, and make sure there is
            # only one
            packages = []
            catch_all = None

            for data in self._xpd.packages():
                name = data['name']

                if 'files' in data:
                    packages.append((name, data))
                elif catch_all is None:
                    catch_all = (name, data)
                else:
                    # Throw an error if we already have a package with that
                    # pattern
                    args = (name, catch_all[0])
                    msg = 'Package %s cannot be grab all files, %s already does'
                    raise Exception(msg % args)

            def get_offsets_for_files(files):
                """
                Get the subset of path offsets needed for these files.
                """

                # Create default empty offset list section
                offset_names = ['binary_files', 'sub_binary_files', 'text_files']
                package_offsets = dict(zip(offset_names, [[]] * 3))
                package_offsets['install_dir'] = install_path_offsets['install_dir']

                # Search the offset list and make sure to include any the
                # offsets for any files found in this package
                for offset_name in offset_names:
                    offset_files = install_path_offsets[offset_name]

                    for f in files:
                        if f in offset_files:
                            package_offsets[offset_name].append(f)

                return package_offsets


            def get_needed_dirs(files):
                """
                Get the set of directories needed (this is O(n^2) in the
                number of files, would be fast with a trie made of the files
                or dirs)
                """
                dirs = []

                for f in files:
                    for d in new_dirs:
                        if f.startswith(d):
                            dirs.append(d)

                return dirs


            # TODO: go through and check if expressions from different packages
            # match all the files and print out a warning
            file_set = set(new_files)
            used_dirs = set()
            infos = []

            # TODO: handle directories

            # Go through the non catch all package gathering up files
            for name, data in packages:
                # Go through and match files
                used_files = set()

                for pattern in data['files']:
                    # Build our pattern
                    regex = re.compile(pattern)

                    # Match against files
                    for f in file_set:
                        match = regex.match(f)

                        # Mark file as used
                        if match and match.span()[1] == len(f):
                            used_files.add(f)

                # Grab the directories needed by this package, and mark them
                # as used
                dirs = get_needed_dirs(used_files)
                used_dirs.update(dirs)

                # Get the install path offsets for this package
                package_offsets = get_offsets_for_files(used_files)

                # Build final info object
                new_info = {
                    'name' : name,
                    'version' : data['version'],
                    'description' : data['description'],
                    'dependencies' : data['dependencies'],
                    'dirs' : dirs,
                    'files' : list(used_files),
                    'install_path_offsets' : package_offsets,
                }

                infos.append(new_info)

                # Remove the used_files from our file set
                file_set = file_set - used_files

            # If we have a catch all
            num_files_left = len(file_set)

            if catch_all:
                if num_files_left == 0:
                    # Warn if we don't have any files
                    print 'WARNING: %d files left un-packaged' % num_files_left
                else:
                    # Otherwise build our info object
                    name, data = catch_all

                    # Get the offsets needed for the files left
                    package_offsets = get_offsets_for_files(file_set)

                    # Get all the directories needed for our files
                    dirs = get_needed_dirs(used_files)
                    used_dirs.update(dirs)

                    # Find out what directories are left
                    unused_dirs = new_dirs - used_dirs

                    new_info = {
                        'name' : name,
                        'version' : data['version'],
                        'description' : data['description'],
                        'dependencies' : data['dependencies'],
                        'dirs' : dirs + list(unused_dirs),
                        'files' : list(file_set),
                        'install_path_offsets' : package_offsets,
                    }

                    infos.append(new_info)
            else:
                # If we don't have a catch all warn we do have files
                if num_files_left > 0:
                     print 'WARNING: %d files left un-packaged' % num_files_left

        return infos


    def _find_path_offsets(self, paths):
        """
        Search the given paths of the packages for instances of the targetdir.
        Here is some example output:

          {
            'install_dir' : '/tmp/xpkg-720617e18f95633fec423f7a522d88eb',
            # The location of the null-terminated install string
            'binary_files' : {
               'bin/hello' : [12947, 57290]
            }
            # The location of the install string and the null of the string
            # it's located in
            'sub_binary_files' : {
               'bin/hello' : [[1000, 1015], [12947, 12965]]
            }
            # The location in each file of the string we have to replace
            'text_files' : {
               'share/hello/message.txt' : [23,105]
            }
          }
        """

        # Get just our files
        install_dir = self._target_dir
        full_paths = [(os.path.join(install_dir, p),p) for p in paths]
        files = [p for p in full_paths
                 if os.path.isfile(p[0]) and not os.path.islink(p[0])]

        # State we are finding
        binary_files = {}
        sub_binary_files = {}
        text_files = {}

        for full_path, filepath in files:
            # Load file into memory
            contents = open(full_path).read()

            # Find the locations of all strings
            offsets = [m.start() for m in re.finditer(install_dir, contents)]

            # Count number of zero bytes to determine if we are binary or not
            # WARNING: this will fail with UTF16 or UTF32 files
            zeros = contents.count('\0')

            if len(offsets) > 0:
                # If we found any record the fact
                if zeros > 0:
                    binary_offsets = []
                    sub_binary_offsets = []
                    prev_null_term = None

                    # Stores each offset as full or a binary substring
                    for offset in offsets:
                        # Find the location of the null termination
                        null_term = contents.find('\0', offset)

                        if null_term == offset + len(install_dir):
                            # Record strings that are just null terminated
                            binary_offsets.append(offset)
                        else:
                            if null_term == prev_null_term:
                                # This is part of the same string as the previous
                                # instance, add to that list
                                sub_binary_offsets[-1].insert(-1, offset)
                            else:
                                # If not record the offset and null location
                                sub_binary_offsets.append([offset, null_term])

                            prev_null_term = null_term

                    # Store our results for this file path if needed
                    if len(binary_offsets) > 0:
                        binary_files[filepath] = binary_offsets

                    if len(sub_binary_offsets) > 0:
                        # Store the results
                        sub_binary_files[filepath] = sub_binary_offsets

                else:
                    # If we have found text files record the fact
                    text_files[filepath] = offsets


        # Form information into a dict return to the user
        results = {
            'install_dir' : install_dir,
            'binary_files' : binary_files,
            'sub_binary_files' : sub_binary_files,
            'text_files' : text_files,
        }

        return results


class BinaryPackageBuilder(object):
    """
    Turns XPD files into binary packages. They are built and installed into a
    temporary directory.

    The binary package format starts with an uncompressed tar file containing:
         xpkg.yml - Contains the package information
         files.tar.gz - Archive of files rooted in the env
    """

    def __init__(self,  package_xpd):
        self._xpd = package_xpd
        self._work_dir = None
        self._target_dir = None


    def build(self, storage_dir, environment=None, output_to_file=True):
        """
        Run the standard PackageBuilder then pack up the results in a package.
        """

        # Create our temporary directory
        name = self._xpd.name
        self._work_dir = tempfile.mkdtemp(suffix = '-xpkg-install-' + name)

        # TODO: make this a hash of something meaning, full
        pad_hash = util.hash_string(name)
        install_dir = os.path.join(self._work_dir, 'install-' + pad_hash)

        # TODO: LOG THIS
        print 'Binary working in:',self._work_dir

        try:
            # Build the package(s)
            builder = PackageBuilder(self._xpd)
            infos = builder.build(install_dir, environment, output_to_file)

            # Build packages and get their paths
            dest_paths = [self._create_package(install_dir, storage_dir, info)
                          for info in infos]

        finally:
            # Make sure we cleanup after we are done
            # Don't do this right now
            shutil.rmtree(self._work_dir)

        return dest_paths

    def _create_package(self, install_dir, storage_dir, info):
        """
        Creates a package from the given package info.

        The path to that archive is returned.
        """

        # Tar up the files
        file_tar = os.path.join(self._work_dir, 'files.tar.gz')

        with tarfile.open(file_tar, "w:gz") as tar:
            for entry_name in info['files']:
                full_path = os.path.join(install_dir, entry_name)
                tar.add(full_path, arcname=entry_name)

        # Create our metadata file
        meta_file = os.path.join(self._work_dir, 'xpkg.yml')
        with open(meta_file, 'w') as f:
            util.yaml_dump(info, f)

        # Create our package
        package_name = self._get_package_name(info)
        package_tar = os.path.join(self._work_dir, package_name)

        with tarfile.open(package_tar, "w") as tar:
            tar.add(meta_file, arcname=os.path.basename(meta_file))
            tar.add(file_tar, arcname=os.path.basename(file_tar))

        # Move to the desired location
        dest_path = os.path.join(storage_dir, package_name)

        if os.path.exists(dest_path):
            os.remove(dest_path)

        shutil.move(package_tar, storage_dir)

        return dest_path


    def _get_package_name(self, info):
        """
        Gets the platform name in the following format:

           <name>_<version>_<arch>_<linkage>_<kernel>.deb

        It's really long, but we want to be able to support all platforms!
        """

        # Use the python platform module to find out about our system
        bits, linkage = platform.architecture()
        arch = platform.machine()
        kernel = platform.system()

        # Build our arguments
        args = {
            'name' : info['name'],
            'version' : info['version'],
            'arch' : arch,
            'linkage' : linkage.lower(),
            'kernel' : kernel.lower(),
        }

        # Create our version
        fmt_str = '%(name)s_%(version)s_%(arch)s_%(linkage)s_%(kernel)s.xpa'

        return fmt_str % args
