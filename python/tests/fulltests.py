# Author: Joseph Lisee <jlisee@gmail.com>

__doc__ = """Really basic full up tests
"""

# Python Imports
import copy
import hashlib
import os
import shutil
import sys
import tempfile
import unittest

cur_dir, _ = os.path.split(__file__)
root_dir = os.path.abspath(os.path.join(cur_dir, '..', '..'))

# Project imports
from xpm import core
from xpm import util
from tests import build_tree


class FullTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        """
        Sets up a little test XPM environment
        """

        # Create test repository
        cls.storage_dir = tempfile.mkdtemp(suffix = '-testing-xpm-repo')

        build_tree.create_test_repo(cls.storage_dir)

        # Provide path to the package description tree
        cls.tree_dir = os.path.join(cls.storage_dir, 'tree')

        # Provide a path to the xpd
        cls.hello_xpd = os.path.join(cls.tree_dir, 'hello.xpd')


    @classmethod
    def tearDownClass(cls):
        """
        Destroys our test xpm environment
        """
        if os.path.exists(cls.storage_dir):
           shutil.rmtree(cls.storage_dir)


    def setUp(self):
        # Create temp dir
        self.work_dir = tempfile.mkdtemp(suffix = '-testing-xpm')
        print self.work_dir

        # Create the env_dir
        self.env_dir = os.path.join(self.work_dir, 'env')

        self.hello_bin = os.path.join(self.env_dir, 'bin', 'hello')

        # Create our binary package repository dir
        self.repo_dir = os.path.join(self.work_dir, 'repo')
        util.ensure_dir(self.repo_dir)

        # Save the environment
        self._env = copy.deepcopy(os.environ)


    def tearDown(self):
        # Remove temp dir
        if os.path.exists(self.work_dir):
           shutil.rmtree(self.work_dir)

        # Purge new environment variables
        for key in os.environ.keys():
            if not key in self._env:
                del os.environ[key]

        # Restore new variables
        for key, val in self._env.iteritems():
            os.environ[key] = val


    def _xpm_cmd(self, args, env_dir=None, use_var=True):
        """
        Run XPM command and return the output.
        """

        # Setup arguments
        if env_dir is None:
            env_dir = self.env_dir

        if use_var:
            env_args = []
            os.environ[core.xpm_root_var] = env_dir
        else:
            # Clear variable
            if core.xpm_root_var in os.environ:
                del os.environ[core.xpm_root_var]

            # Set out args
            env_args = ['--root',env_dir]

        # Run command and return the results
        cmd = [os.path.join(root_dir, 'xpm')] + args + env_args

        return util.shellcmd(cmd, shell=False, stream=False)


    def test_no_env(self):
        """
        Make sure we get an error when there is no environment.
        """

        env_dir = os.path.join(self.work_dir, 'env')

        output = self._xpm_cmd(['list'])

        self.assertRegexpMatches(output, 'No XPM package DB found in root.*')


    def test_install(self):
        """
        Make sure the desired program was installed and works.
        """

        # Run the install
        self._xpm_cmd(['install', self.hello_xpd])

        # Run our program to make sure it works
        output = util.shellcmd(self.hello_bin, echo=False)

        self.assertEqual('Hello, world!\n', output)


    def test_install_with_tree_flag(self):
        """
        Make sure we can install with the package tree.
        """

        # Run the install
        self._xpm_cmd(['install', 'hello', '--tree', self.tree_dir])

        # Run our program to make sure it works
        self.assertTrue(os.path.exists(self.hello_bin))


    def test_install_with_tree_var(self):
        """
        Make sure we can install with the package tree.
        """

        # Set our environment variable
        os.environ[core.xpm_tree_var] = self.tree_dir

        # Run the install
        self._xpm_cmd(['install', 'hello'])

        # Run our program to make sure it works
        self.assertTrue(os.path.exists(self.hello_bin))


    def test_install_with_tree_repo(self):
        """
        Make sure we can install with the package tree.
        """

        # Build our package
        self._xpm_cmd(['build', self.hello_xpd, '--dest', self.repo_dir])

        # Run the install
        os.environ[core.xpm_repo_var] = self.repo_dir

        self._xpm_cmd(['install', 'hello'])

        # Run our program to make sure it works
        self.assertTrue(os.path.exists(self.hello_bin))


    def test_info(self):
        """
        Makes sure we can get the proper information back about an installed
        package.
        """

        self._xpm_cmd(['install', self.hello_xpd])

        output = self._xpm_cmd(['info', 'hello'], use_var=False)

        self.assertEqual('Package hello at version 1.0.0\n', output)


    def test_info_root_args(self):
        """
        Make sure we can pass the root with the command line flag.
        """

        self._xpm_cmd(['install', self.hello_xpd])

        # Make sure the info command returns the right data
        output = self._xpm_cmd(['info', 'hello'], )

        self.assertEqual('Package hello at version 1.0.0\n', output)


    def test_remove(self):

        # Install the package
        self._xpm_cmd(['install', self.hello_xpd])

        # Get the package list
        output = self._xpm_cmd(['list'])

        self.assertEqual('  hello - 1.0.0\n', output)

        # Un-install the package
        self._xpm_cmd(['remove', 'hello'])

        self.assertFalse(os.path.exists(self.hello_bin))


    def test_jump(self):
        # Create and empty db files
        db_dir = os.path.join(self.env_dir, 'etc', 'xpm',)
        util.ensure_dir(db_dir)

        db_path = os.path.join(db_dir, 'db.yml')
        util.touch(db_path)

        # Test ENV_ROOT
        def get_var(varname):
            py_command = 'python -c "import os; print os.environ[\'%s\']"' % varname

            return self._xpm_cmd(['jump', '-c', py_command]).strip()

        self.assertEquals(self.env_dir, get_var(core.xpm_root_var))

        # Make sure PATH is set
        path = get_var('PATH')
        paths = path.split(os.pathsep)

        bin_dir = os.path.join(self.env_dir, 'bin')

        self.assertEqual(1, paths.count(bin_dir))
        self.assertTrue(path.startswith(bin_dir))

        # Make sure LD_LIBRARY_PATH is set
        path = get_var('LD_LIBRARY_PATH')
        paths = path.split(os.pathsep)

        lib_dir = os.path.join(self.env_dir, 'lib')

        self.assertEqual(1, paths.count(lib_dir))
        self.assertTrue(path.startswith(lib_dir))


    def test_build(self):
        # Build our package
        self._xpm_cmd(['build', self.hello_xpd, '--dest', self.repo_dir])

        # Get the path to the created package
        new_files = os.listdir(self.repo_dir)

        self.assertEqual(1, len(new_files))

        pkg_path = os.path.join(self.repo_dir, new_files[0])

        # Install the package
        self._xpm_cmd(['install', pkg_path])

        # Make sure the package is in the info
        output = self._xpm_cmd(['info', 'hello'], )

        self.assertEqual('Package hello at version 1.0.0\n', output)

        # Make sure the actual binary exists
        self.assertTrue(os.path.exists(self.hello_bin))


if __name__ == '__main__':
    unittest.main()
