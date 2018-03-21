"""
Defines a set of regressions tests that should be run succesfully before
anything is pushed to the central repository.
"""
from __future__ import absolute_import, division, print_function, unicode_literals
import unittest
import sys

import numpy as np
from numpy.random import RandomState

from ase import Atoms
from ase.build import bcc100, molecule
from ase.visualize import view
import ase.build
from ase.build import nanotube
import ase.lattice.hexagonal
from ase.lattice.compounds import Zincblende
from ase.lattice.cubic import SimpleCubicFactory
import ase.io
import json

from systax import Classifier
from systax import PeriodicFinder
from systax.classifications import \
    Class0D, \
    Class1D, \
    Class2D, \
    Class3D, \
    Atom, \
    Molecule, \
    Crystal, \
    Material1D, \
    Material2D, \
    Unknown, \
    Surface
from systax import Class3DAnalyzer
from systax.data.constants import WYCKOFF_LETTER_POSITIONS
import systax.geometry


class dotdict(dict):
    """dot.notation access to dictionary attributes"""
    __getattr__ = dict.get
    __setattr__ = dict.__setitem__
    __delattr__ = dict.__delitem__


def get_atoms_from_viz(filename):
    """Used to construct an ase.Atoms from a custom visualization file.
    """
    with open(filename, "r") as fin:
        data = json.load(fin)
    pos = data["positions"]
    cell = data["normalizedCell"]
    num = data["labels"]

    atoms = Atoms(
        scaled_positions=pos,
        cell=1e10*np.array(cell),
        symbols=num,
        pbc=True
    )

    return atoms


def get_atoms_from_arch(filename):
    """Used to construct an ase.Atoms from a NOMAD Archive file.
    """
    with open(filename, "r") as fin:
        data = json.load(fin)
    section_system = data["sections"]["section_run-0"]["sections"]["section_system-0"]

    atoms = Atoms(
        positions=1e10*np.array(section_system["atom_positions"]),
        cell=1e10*np.array(section_system["simulation_cell"]),
        symbols=section_system["atom_labels"],
        pbc=True,
    )

    return atoms


class ExceptionTests(unittest.TestCase):
    """Tests for exceptions that arise from invalid arguments.
    """
    def test_too_many_atoms(self):
        system = bcc100('Fe', size=(11, 10, 10), vacuum=8)

        classifier = Classifier()
        with self.assertRaises(ValueError):
            classifier.classify(system)


class GeometryTests(unittest.TestCase):
    """Tests for the geometry module.
    """
    def test_thickness(self):
        """Getting the thickness of structures.
        """
        sys = molecule("H2O")
        thickness_x = systax.geometry.get_thickness(sys, 0)
        self.assertEqual(thickness_x, 0)

        thickness_y = systax.geometry.get_thickness(sys, 1)
        self.assertEqual(thickness_y, 1.526478)

        thickness_z = systax.geometry.get_thickness(sys, 2)
        self.assertEqual(thickness_z, 0.596309)

    def test_minimize_cell(self):
        """Cell minimization.
        """
        sys = molecule("H2O")
        sys.set_cell([3, 3, 3])

        # Minimize with minimum size smaller than found minimum size
        minimized_system = systax.geometry.get_minimized_cell(sys, 2, 0.1)
        cell = minimized_system.get_cell()
        pos = minimized_system.get_scaled_positions()
        expected_cell = np.array([
            [3., 0., 0.],
            [0., 3., 0.],
            [0., 0., 0.596309]
        ])
        expected_pos = np.array([
            [0., 0., 1.],
            [0., 0.254413, 0.],
            [0., -0.254413, 0.]
        ])
        self.assertTrue(np.allclose(expected_cell, cell, atol=0.001, rtol=0))
        self.assertTrue(np.allclose(expected_pos, pos, atol=0.001, rtol=0))

        # Minimize with minimum size larger than found minimum size
        minimized_system = systax.geometry.get_minimized_cell(sys, 2, 2)
        cell = minimized_system.get_cell()
        pos = minimized_system.get_scaled_positions()
        expected_cell = np.array([
            [3., 0., 0.],
            [0., 3., 0.],
            [0., 0., 2.]
        ])
        expected_pos = np.array([
            [0., 0., 0.64907725],
            [0., 0.254413, 0.35092275],
            [0., -0.254413, 0.35092275]
        ])
        self.assertTrue(np.allclose(expected_cell, cell, atol=0.001, rtol=0))
        self.assertTrue(np.allclose(expected_pos, pos, atol=0.001, rtol=0))

    def test_center_of_mass(self):
        """Tests that the center of mass correctly takes periodicity into
        account.
        """
        system = bcc100('Fe', size=(3, 3, 4), vacuum=8)
        adsorbate = ase.Atom(position=[4, 4, 4], symbol="H")
        system += adsorbate
        system.set_pbc([True, True, True])
        system.translate([0, 0, 10])
        system.wrap()
        # view(system)

        # Test periodic COM
        cm = systax.geometry.get_center_of_mass(system)
        self.assertTrue(np.allclose(cm, [4., 4., 20.15], atol=0.1))

        # Test finite COM
        system.set_pbc(False)
        cm = systax.geometry.get_center_of_mass(system)
        self.assertTrue(np.allclose(cm, [3.58770672, 3.58770672, 10.00200455], atol=0.1))

    def test_matches_non_orthogonal(self):
        """Test that the correct factor is returned when finding matches that
        are in the neighbouring cells.
        """
        system = ase.build.mx2(
            formula="MoS2",
            kind="2H",
            a=3.18,
            thickness=3.19,
            size=(5, 5, 1),
            vacuum=8)
        system.set_pbc(True)
        system = system[[0, 12]]
        # view(system)

        searched_pos = system.get_positions()[0][None, :]
        basis = np.array([[1.59, -2.75396078, 0]])
        searched_pos += basis

        matches, subst, vac, factors = systax.geometry.get_matches(
            system,
            searched_pos,
            numbers=[system.get_atomic_numbers()[0]],
            tolerances=np.array([0.2])
        )

        # Make sure that the atom is found in the correct copy
        self.assertEqual(tuple(factors[0]), (0, -1, 0))

        # Make sure that the correct atom is found
        self.assertTrue(np.array_equal(matches, [1]))

    def test_displacement_non_orthogonal(self):
        """Test that the correct displacement is returned when the cell in
        non-orthorhombic.
        """
        positions = np.array([
            [1.56909, 2.71871, 6.45326],
            [3.9248, 4.07536, 6.45326]
        ])
        cell = np.array([
            [4.7077, -2.718, 0.],
            [0., 8.15225, 0.],
            [0., 0., 50.]
        ])

        # Fully periodic with minimum image convention
        dist_mat = systax.geometry.get_distance_matrix(
            positions[0, :],
            positions[1, :],
            cell,
            pbc=True,
            mic=True)

        # The minimum image should be within the same cell
        expected = np.linalg.norm(positions[0, :] - positions[1, :])
        self.assertTrue(np.allclose(dist_mat[0], expected))

    def test_distance_matrix(self):
        pos1 = np.array([
            [0, 0, 0],
        ])
        pos2 = np.array([
            [0, 0, 7],
            [6, 0, 0],
        ])
        cell = np.array([
            [7, 0, 0],
            [0, 7, 0],
            [0, 0, 7]
        ])

        # Non-periodic
        dist_mat = systax.geometry.get_distance_matrix(pos1, pos2)
        expected = np.array(
            [[7, 6]]
        )
        self.assertTrue(np.allclose(dist_mat, expected))

        # Fully periodic with minimum image convention
        dist_mat = systax.geometry.get_distance_matrix(pos1, pos2, cell, pbc=True, mic=True)
        expected = np.array(
            [[0, 1]]
        )
        self.assertTrue(np.allclose(dist_mat, expected))

        # Partly periodic with minimum image convention
        dist_mat = systax.geometry.get_distance_matrix(pos1, pos2, cell, pbc=[False, True, True], mic=True)
        expected = np.array(
            [[0, 6]]
        )
        self.assertTrue(np.allclose(dist_mat, expected))

    def test_displacement_tensor(self):
        # Non-periodic
        cell = np.array([
            [1, 0, 0],
            [0, 1, 0],
            [0, 0, 1]
        ])
        pos1 = np.array([
            [0, 0, 0],
        ])
        pos2 = np.array([
            [1, 1, 1],
            [0.9, 0, 0],
        ])

        disp_tensor = systax.geometry.get_displacement_tensor(pos1, pos2)
        expected = np.array(-pos2)
        self.assertTrue(np.allclose(disp_tensor, expected))

        # Fully periodic
        disp_tensor = systax.geometry.get_displacement_tensor(pos1, pos2, pbc=True, cell=cell, mic=True)
        expected = np.array([[
            [0, 0, 0],
            [0.1, 0, 0],
        ]])
        self.assertTrue(np.allclose(disp_tensor, expected))

        # Fully periodic, reversed direction
        disp_tensor = systax.geometry.get_displacement_tensor(pos2, pos1, pbc=True, cell=cell, mic=True)
        expected = np.array([[
            [0, 0, 0],
        ], [
            [-0.1, 0, 0],
        ]])
        self.assertTrue(np.allclose(disp_tensor, expected))

        # Periodic in one direction
        disp_tensor = systax.geometry.get_displacement_tensor(pos1, pos2, pbc=[True, False, False], cell=cell, mic=True)
        expected = np.array([[
            [0, -1, -1],
            [0.1, 0, 0],
        ]])
        self.assertTrue(np.allclose(disp_tensor, expected))

    def test_to_cartesian(self):
        # Inside, unwrapped
        cell = np.array([
            [1, 1, 0],
            [0, 2, 0],
            [1, 0, 1]
        ])
        rel_pos = np.array([
            [0, 0, 0],
            [1, 1, 1],
            [0.5, 0.5, 0.5],
        ])
        expected_pos = np.array([
            [0, 0, 0],
            [2, 3, 1],
            [1, 1.5, 0.5],
        ])
        cart_pos = systax.geometry.to_cartesian(cell, rel_pos)
        self.assertTrue(np.allclose(cart_pos, expected_pos))

        # Outside, unwrapped
        cell = np.array([
            [1, 1, 0],
            [0, 2, 0],
            [1, 0, 1]
        ])
        rel_pos = np.array([
            [0, 0, 0],
            [2, 2, 2],
            [0.5, 1.5, 0.5],
        ])
        expected_pos = np.array([
            [0, 0, 0],
            [4, 6, 2],
            [1, 3.5, 0.5],
        ])
        cart_pos = systax.geometry.to_cartesian(cell, rel_pos)
        self.assertTrue(np.allclose(cart_pos, expected_pos))

        # Outside, wrapped
        cell = np.array([
            [1, 1, 0],
            [0, 2, 0],
            [1, 0, 1]
        ])
        rel_pos = np.array([
            [0, 0, 0],
            [2, 2, 2],
            [0.5, 1.5, 0.5],
        ])
        expected_pos = np.array([
            [0, 0, 0],
            [0, 0, 0],
            [1, 1.5, 0.5],
        ])
        cart_pos = systax.geometry.to_cartesian(cell, rel_pos, wrap=True, pbc=True)
        self.assertTrue(np.allclose(cart_pos, expected_pos))


class DimensionalityTests(unittest.TestCase):
    """Unit tests for finding the dimensionality of different systems.
    """
    # Read the defaults
    classifier = Classifier()
    cluster_threshold = classifier.cluster_threshold

    # 0D system
    sys0d = molecule("H2O")
    sys0d.set_pbc([False, False, False])
    sys0d.set_cell([3, 3, 3])
    sys0d.center()

    # 1D system
    sys1d = nanotube(3, 3, length=6, bond=1.4, symbol='Si')
    sys1d.set_pbc([True, True, True])
    sys1d.set_cell((10, 10, 15))
    sys1d.center()

    # 2D system
    sys2d = Atoms(
        symbols=[6, 6],
        cell=np.array((
            [2.4595121467478055, 0.0, 0.0],
            [-1.2297560733739028, 2.13, 0.0],
            [0.0, 0.0, 10.0]
        )),
        scaled_positions=np.array((
            [0.3333333333333333, 0.6666666666666666, 0.5],
            [0.6666666666666667, 0.33333333333333337, 0.5]
        )),
    )
    sys2d = sys2d.repeat((3, 3, 1))

    # 3D system
    sys3d = ase.lattice.cubic.Diamond(
        size=(1, 1, 1),
        symbol='Si',
        pbc=True,
        latticeconstant=5.430710)

    def test_0d_n_pbc0(self):
        dimensionality = systax.geometry.get_dimensionality(
            DimensionalityTests.sys0d,
            DimensionalityTests.cluster_threshold)
        self.assertEqual(dimensionality, 0)

    def test_0d_n_pbc3(self):
        DimensionalityTests.sys1d.set_pbc([True, True, True])
        dimensionality = systax.geometry.get_dimensionality(
            DimensionalityTests.sys0d,
            DimensionalityTests.cluster_threshold)
        self.assertEqual(dimensionality, 0)

    def test_1d_n_pbc3(self):
        DimensionalityTests.sys1d.set_pbc([True, True, True])
        dimensionality = systax.geometry.get_dimensionality(
            DimensionalityTests.sys1d,
            DimensionalityTests.cluster_threshold)
        self.assertEqual(dimensionality, 1)

    def test_1d_n_pbc2(self):
        DimensionalityTests.sys1d.set_pbc([False, True, True])
        dimensionality = systax.geometry.get_dimensionality(
            DimensionalityTests.sys1d,
            DimensionalityTests.cluster_threshold)
        self.assertEqual(dimensionality, 1)

    def test_1d_n_pbc1(self):
        DimensionalityTests.sys1d.set_pbc([False, False, True])
        dimensionality = systax.geometry.get_dimensionality(
            DimensionalityTests.sys1d,
            DimensionalityTests.cluster_threshold)
        self.assertEqual(dimensionality, 1)

    def test_2d_n_pbc3(self):
        DimensionalityTests.sys2d.set_pbc([True, True, True])
        dimensionality = systax.geometry.get_dimensionality(
            DimensionalityTests.sys2d,
            DimensionalityTests.cluster_threshold)
        self.assertEqual(dimensionality, 2)

    def test_2d_n_pbc2(self):
        DimensionalityTests.sys2d.set_pbc([True, True, False])
        dimensionality = systax.geometry.get_dimensionality(
            DimensionalityTests.sys2d,
            DimensionalityTests.cluster_threshold)
        self.assertEqual(dimensionality, 2)

    def test_3d_n_pbc3(self):
        dimensionality = systax.geometry.get_dimensionality(
            DimensionalityTests.sys3d,
            DimensionalityTests.cluster_threshold)
        self.assertEqual(dimensionality, 3)

    def test_non_orthogonal_crystal(self):
        """Test a system that has a non-orthogonal cell.
        """
        system = get_atoms_from_arch("./structures/PSX9X4dQR2r1cjQ9kBtuC-wI6MO8B.json")
        dimensionality = systax.geometry.get_dimensionality(
            system,
            DimensionalityTests.cluster_threshold
        )
        self.assertEqual(dimensionality, 3)

    def test_surface_split(self):
        """Test a surface that has been split by the cell boundary
        """
        system = bcc100('Fe', size=(5, 1, 3), vacuum=8)
        system.translate([0, 0, 9])
        system.set_pbc(True)
        system.wrap(pbc=True)
        dimensionality = systax.geometry.get_dimensionality(
            system,
            DimensionalityTests.cluster_threshold)
        self.assertEqual(dimensionality, 2)

    def test_surface_wavy(self):
        """Test a surface with a high amplitude wave. This would break a
        regular linear vacuum gap search.
        """
        system = bcc100('Fe', size=(15, 3, 3), vacuum=8)
        pos = system.get_positions()
        x_len = np.linalg.norm(system.get_cell()[0, :])
        x = pos[:, 0]
        z = pos[:, 2]
        z_new = z + 3*np.sin(4*(x/x_len)*np.pi)
        pos_new = np.array(pos)
        pos_new[:, 2] = z_new
        system.set_positions(pos_new)
        system.set_pbc(True)
        # view(system)
        dimensionality = systax.geometry.get_dimensionality(
            system,
            DimensionalityTests.cluster_threshold)
        self.assertEqual(dimensionality, 2)

    def test_graphite(self):
        system = ase.lattice.hexagonal.Graphite(
            size=(1, 1, 1),
            symbol='C',
            pbc=True,
            latticeconstant=(2.461, 6.708))
        # view(system)
        dimensionality = systax.geometry.get_dimensionality(
            system,
            DimensionalityTests.cluster_threshold)
        self.assertEqual(dimensionality, 3)


class PeriodicFinderTests(unittest.TestCase):
    """Unit tests for the class that is used to find periodic regions.
    """
    classifier = Classifier()
    max_cell_size = classifier.max_cell_size
    angle_tol = classifier.angle_tol
    delaunay_threshold = classifier.delaunay_threshold
    bond_threshold = classifier.bond_threshold
    pos_tol = classifier.pos_tol
    pos_tol_scaling = classifier.pos_tol_scaling
    cell_size_tol = classifier.cell_size_tol

    def test_cell_selection(self):
        """Testing that the correct cell is selected.
        """
        # 3D: Selecting orthogonal from two options with same volume
        spans = np.array([
            [1, 0, 0],
            [0, 1, 0],
            [0, 0, 1],
            [0, 2, 1],
        ])
        metrics = np.array([0, 0, 0, 0])

        finder = PeriodicFinder()
        indices = finder._find_best_basis(spans, metrics)
        self.assertTrue(np.array_equal(indices, np.array([0, 1, 2])))

        # 3D: Selecting the non-orthogonal because another combination has higer
        # periodicity
        spans = np.array([
            [1, 0, 0],
            [0, 1, 0],
            [0, 0, 1],
            [0, 2, 1],
        ])
        metrics = np.array([2, 2, 1, 2])

        finder = PeriodicFinder()
        indices = finder._find_best_basis(spans, metrics)
        self.assertTrue(np.array_equal(indices, np.array([0, 1, 3])))

        # 3D: Selecting first by volume, then by orthogonality.
        spans = np.array([
            [1, 0, 0],
            [0, 1, 0],
            [0, 0, 1],
            [0, 0.5, 0.5],
        ])
        metrics = np.array([0, 0, 0, 0])

        finder = PeriodicFinder()
        indices = finder._find_best_basis(spans, metrics)
        self.assertTrue(np.array_equal(indices, np.array([0, 1, 3])))

        # 2D: Selecting orthogonal from two options with same volume
        spans = np.array([
            [1, 0, 0],
            [0, 1, 0],
            [1, 1, 0],
        ])
        metrics = np.array([0, 0, 0])

        finder = PeriodicFinder()
        indices = finder._find_best_basis(spans, metrics)
        self.assertTrue(np.array_equal(indices, np.array([0, 1])))

        # 2D: Selecting the non-orthogonal because another combination has higer
        # periodicity
        spans = np.array([
            [1, 0, 0],
            [0, 1, 0],
            [1, 2, 0],
        ])
        metrics = np.array([2, 1, 2])

        finder = PeriodicFinder()
        indices = finder._find_best_basis(spans, metrics)
        self.assertTrue(np.array_equal(indices, np.array([0, 2])))

        # 2D: Selecting first by area, then by orthogonality.
        spans = np.array([
            [1, 0, 0],
            [0, 1, 0],
            [0, 0.5, 0],
        ])
        metrics = np.array([0, 0, 0])

        finder = PeriodicFinder()
        indices = finder._find_best_basis(spans, metrics)
        self.assertTrue(np.array_equal(indices, np.array([0, 2])))

    # def test_proto_cell_in_curved(self):
        # """Tests that the relative positions in the prototype cell are found
        # robustly even in distorted cells.
        # """
        # # Create an Fe 100 surface as an ASE Atoms object
        # class NaClFactory(SimpleCubicFactory):
            # "A factory for creating NaCl (B1, Rocksalt) lattices."

            # bravais_basis = [[0, 0, 0], [0, 0, 0.5], [0, 0.5, 0], [0, 0.5, 0.5],
                            # [0.5, 0, 0], [0.5, 0, 0.5], [0.5, 0.5, 0],
                            # [0.5, 0.5, 0.5]]
            # element_basis = (0, 1, 1, 0, 1, 0, 0, 1)

        # system = NaClFactory()
        # system = system(symbol=["Na", "Cl"], latticeconstant=5.64)
        # system = system.repeat((4, 4, 1))
        # cell = system.get_cell()
        # cell[2, :] *= 3
        # system.set_cell(cell)
        # system.center()

        # # Bulge the surface
        # cell_width = np.linalg.norm(system.get_cell()[0, :])
        # for atom in system:
            # pos = atom.position
            # distortion_z = 0.6*np.cos(pos[0]/cell_width*2.0*np.pi)
            # pos += np.array((0, 0, distortion_z))
        # # view(system)

        # # Classified as surface
        # classifier = Classifier()
        # classification = classifier.classify(system)
        # self.assertIsInstance(classification, Surface)

        # # No defects or unknown atoms
        # adsorbates = classification.adsorbates
        # interstitials = classification.interstitials
        # substitutions = classification.substitutions
        # vacancies = classification.vacancies
        # self.assertEqual(len(interstitials), 0)
        # self.assertEqual(len(substitutions), 0)
        # self.assertEqual(len(vacancies), 0)
        # self.assertEqual(len(adsorbates), 0)

        # # Test that the relative positions are robust in the prototype cell
        # proto_cell = classification.region.cell
        # # view(proto_cell)
        # relative_pos = proto_cell.get_scaled_positions()
        # assumed_pos = np.array([
            # [0.5, 0.0, 0.5],
            # [0, 0, 0],
        # ])
        # self.assertTrue(np.allclose(relative_pos, assumed_pos, atol=0.1))

    # def test_cell_2d_adsorbate(self):
        # """Test that the cell is correctly identified even if adsorbates are
        # near.
        # """
        # system = ase.build.mx2(
            # formula="MoS2",
            # kind="2H",
            # a=3.18,
            # thickness=3.19,
            # size=(5, 5, 1),
            # vacuum=8)
        # system.set_pbc(True)

        # ads = molecule("C6H6")
        # ads.translate([4.9, 5.5, 13])
        # system += ads
        # # view(system)

        # classifier = Classifier()
        # classification = classifier.classify(system)
        # self.assertIsInstance(classification, Material2D)

        # # One adsorbate
        # adsorbates = classification.adsorbates
        # interstitials = classification.interstitials
        # substitutions = classification.substitutions
        # vacancies = classification.vacancies
        # self.assertEqual(len(interstitials), 0)
        # self.assertEqual(len(substitutions), 0)
        # self.assertEqual(len(vacancies), 0)
        # self.assertEqual(len(adsorbates), 12)
        # self.assertTrue(np.array_equal(adsorbates, range(75, 87)))

    # def test_random(self):
        # """Test a structure with random atom positions.
        # """
        # n_atoms = 50
        # rng = RandomState(8)
        # for i in range(10):
            # rand_pos = rng.rand(n_atoms, 3)

            # system = Atoms(
                # scaled_positions=rand_pos,
                # cell=(10, 10, 10),
                # symbols=n_atoms*['C'],
                # pbc=(1, 1, 1))

            # classifier = Classifier()
            # classification = classifier.classify(system)
            # self.assertIsInstance(classification, Class3D)

    # def test_nanocluster(self):
        # """Test the periodicity finder on an artificial perfect nanocluster.
        # """
        # system = bcc100('Fe', size=(7, 7, 12), vacuum=0)
        # system.set_cell([30, 30, 30])
        # system.set_pbc(True)
        # system.center()

        # # Make the thing spherical
        # center = np.array([15, 15, 15])
        # pos = system.get_positions()
        # dist = np.linalg.norm(pos - center, axis=1)
        # valid_ind = dist < 10
        # system = system[valid_ind]

        # # Get the index of the atom that is closest to center of mass
        # cm = system.get_center_of_mass()
        # seed_index = np.argmin(np.linalg.norm(pos-cm, axis=1))
        # # view(system)

        # # Find the region with periodicity
        # finder = PeriodicFinder()
        # region = finder.get_region(
            # system,
            # seed_index,
            # pos_tol=0.01,
            # max_cell_size=4,
        # )

        # # No defects or unknown atoms
        # adsorbates = region.get_adsorbates()
        # interstitials = region.get_interstitials()
        # substitutions = region.get_substitutions()
        # vacancies = region.get_vacancies()
        # self.assertEqual(len(interstitials), 0)
        # self.assertEqual(len(substitutions), 0)
        # self.assertEqual(len(vacancies), 0)
        # self.assertEqual(len(adsorbates), 0)

    # def test_optimized_nanocluster(self):
        # """Test the periodicity finder on a DFT-optimized nanocluster.
        # """
        # system = ase.io.read("./structures/cu55.xyz")
        # system.set_cell([20, 20, 20])
        # system.set_pbc(True)
        # system.center()

        # # Get the index of the atom that is closest to center of mass
        # cm = system.get_center_of_mass()
        # pos = system.get_positions()
        # seed_index = np.argmin(np.linalg.norm(pos-cm, axis=1))
        # view(system)

        # # Find the region with periodicity
        # finder = PeriodicFinder()
        # region = finder.get_region(system, seed_index, 4, 2.75)
        # # print(region)

        # rec = region.recreate_valid()
        # view(rec)
        # # view(rec.unit_cell)

        # # No defects or unknown atoms
        # adsorbates = region.get_adsorbates()
        # interstitials = region.get_interstitials()
        # substitutions = region.get_substitutions()
        # vacancies = region.get_vacancies()
        # unknowns = region.get_unknowns()
        # self.assertEqual(len(interstitials), 0)
        # self.assertEqual(len(substitutions), 0)
        # self.assertEqual(len(vacancies), 0)
        # self.assertEqual(len(adsorbates), 0)
        # self.assertEqual(len(unknowns), 0)


class DelaunayTests(unittest.TestCase):
    """Tests for the Delaunay triangulation.
    """
    classifier = Classifier()
    delaunay_threshold = classifier.delaunay_threshold

    def test_surface(self):
        system = bcc100('Fe', size=(5, 5, 3), vacuum=8)
        # view(system)
        decomposition = systax.geometry.get_tetrahedra_decomposition(
            system,
            DelaunayTests.delaunay_threshold
        )

        # Atom inside
        test_pos = np.array([7, 7, 9.435])
        self.assertNotEqual(decomposition.find_simplex(test_pos), None)

        # Atoms at the edges should belong to the surface
        test_pos = np.array([14, 2, 9.435])
        self.assertNotEqual(decomposition.find_simplex(test_pos), None)
        test_pos = np.array([1.435, 13, 9.435])
        self.assertNotEqual(decomposition.find_simplex(test_pos), None)

        # Atoms outside
        test_pos = np.array([5, 5, 10.9])
        self.assertEqual(decomposition.find_simplex(test_pos), None)
        test_pos = np.array([5, 5, 7.9])
        self.assertEqual(decomposition.find_simplex(test_pos), None)

    def test_2d(self):
        system = ase.build.mx2(
            formula="MoS2",
            kind="2H",
            a=3.18,
            thickness=3.19,
            size=(2, 2, 1),
            vacuum=8)
        system.set_pbc(True)
        # view(system)

        decomposition = systax.geometry.get_tetrahedra_decomposition(
            system,
            DelaunayTests.delaunay_threshold
        )

        # Atom inside
        test_pos = np.array([2, 2, 10])
        self.assertNotEqual(decomposition.find_simplex(test_pos), None)
        test_pos = np.array([2, 2, 10.5])
        self.assertNotEqual(decomposition.find_simplex(test_pos), None)

        # # Atoms at the edges should belong to the surface
        test_pos = np.array([0, 4, 10])
        self.assertNotEqual(decomposition.find_simplex(test_pos), None)
        test_pos = np.array([5, 1, 10])
        self.assertNotEqual(decomposition.find_simplex(test_pos), None)

        # # Atoms outside
        test_pos = np.array([2, 2, 11.2])
        self.assertEqual(decomposition.find_simplex(test_pos), None)
        test_pos = np.array([0, 0, 7.9])
        self.assertEqual(decomposition.find_simplex(test_pos), None)


class AtomTests(unittest.TestCase):
    """Tests for detecting an Atom.
    """
    def test_finite(self):
        classifier = Classifier()
        c = Atoms(symbols=["C"], positions=np.array([[0.0, 0.0, 0.0]]), pbc=False)
        clas = classifier.classify(c)
        self.assertIsInstance(clas, Atom)

    def test_periodic(self):
        classifier = Classifier()
        c = Atoms(symbols=["C"], positions=np.array([[0.0, 0.0, 0.0]]), pbc=True, cell=[10, 10, 10])
        clas = classifier.classify(c)
        self.assertIsInstance(clas, Atom)

        c = Atoms(symbols=["C"], positions=np.array([[0.0, 0.0, 0.0]]), pbc=[1, 0, 1], cell=[10, 10, 10])
        clas = classifier.classify(c)
        self.assertIsInstance(clas, Atom)

        c = Atoms(symbols=["C"], positions=np.array([[0.0, 0.0, 0.0]]), pbc=[1, 0, 0], cell=[10, 10, 10])
        clas = classifier.classify(c)
        self.assertIsInstance(clas, Atom)


class Class0DTests(unittest.TestCase):
    """Tests for detecting zero-dimensional systems.
    """
    def test_h2o_no_pbc(self):
        h2o = molecule("H2O")
        classifier = Classifier()
        clas = classifier.classify(h2o)
        self.assertIsInstance(clas, Class0D)

    def test_h2o_pbc(self):
        h2o = molecule("CH4")
        gap = 10
        h2o.set_cell([[gap, 0, 0], [0, gap, 0], [0, 0, gap]])
        h2o.set_pbc([True, True, True])
        h2o.center()
        classifier = Classifier()
        clas = classifier.classify(h2o)
        self.assertIsInstance(clas, Class0D)

    def test_unknown_molecule(self):
        """An unknown molecule should be classified as Class0D
        """
        sys = Atoms(
            positions=[[0.0, 0.0, 0.0], [2.0, 0.0, 0.0]],
            symbols=["Au", "Ag"]
        )
        gap = 12
        sys.set_cell([[gap, 0, 0], [0, gap, 0], [0, 0, gap]])
        sys.set_pbc([True, True, True])
        sys.center()
        # view(sys)
        classifier = Classifier()
        clas = classifier.classify(sys)
        self.assertIsInstance(clas, Class0D)


class Class1DTests(unittest.TestCase):
    """Tests detection of one-dimensional structures.
    """
    def test_nanotube_full_pbc(self):
        tube = nanotube(6, 0, length=1)
        tube.set_pbc([True, True, True])
        cell = tube.get_cell()
        cell[0][0] = 20
        cell[1][1] = 20
        tube.set_cell(cell)
        tube.center()

        classifier = Classifier()
        clas = classifier.classify(tube)
        self.assertIsInstance(clas, Class1D)

    def test_nanotube_partial_pbc(self):
        tube = nanotube(6, 0, length=1)
        tube.set_pbc([False, False, True])
        cell = tube.get_cell()
        cell[0][0] = 6
        cell[1][1] = 6
        tube.set_cell(cell)
        tube.center()

        classifier = Classifier()
        clas = classifier.classify(tube)
        self.assertIsInstance(clas, Class1D)

    def test_nanotube_full_pbc_shaken(self):
        tube = nanotube(6, 0, length=1)
        tube.set_pbc([True, True, True])
        cell = tube.get_cell()
        cell[0][0] = 20
        cell[1][1] = 20
        tube.set_cell(cell)
        tube.rattle(0.1, seed=42)
        tube.center()

        classifier = Classifier()
        clas = classifier.classify(tube)
        self.assertIsInstance(clas, Class1D)

    def test_nanotube_too_big(self):
        """Test that too big 1D structures are classifed as unknown.
        """
        tube = nanotube(20, 0, length=1)
        tube.set_pbc([True, True, True])
        cell = tube.get_cell()
        cell[0][0] = 40
        cell[1][1] = 40
        tube.set_cell(cell)
        tube.center()

        classifier = Classifier()
        clas = classifier.classify(tube)
        self.assertIsInstance(clas, Class1D)


class Material2DTests(unittest.TestCase):
    """Tests detection of 2D structures.
    """
    graphene = Atoms(
        symbols=[6, 6],
        cell=np.array((
            [2.4595121467478055, 0.0, 0.0],
            [-1.2297560733739028, 2.13, 0.0],
            [0.0, 0.0, 20.0]
        )),
        scaled_positions=np.array((
            [0.3333333333333333, 0.6666666666666666, 0.5],
            [0.6666666666666667, 0.33333333333333337, 0.5]
        )),
        pbc=True
    )

    # def test_2d_adsorption_small_cell(self):
        # """This test does not currently pass, because for too small cells the
        # adsorbate cannot be determined. This could be fixed by using a smaller
        # max_cell_size when such a case is detected.
        # """
        # system = Material2DTests.graphene.repeat([2, 2, 1])
        # system.set_pbc([True, True, True])
        # adsorbate = ase.Atom(position=[2, 2, 11], symbol="H")
        # system += adsorbate
        # # view(system)

        # classifier = Classifier()
        # classification = classifier.classify(system)
        # self.assertIsInstance(classification, Material2D)
        # unit_cell = classification.region.cell
        # # view(unit_cell)

        # # One outlier
        # outliers = classification.outliers
        # self.assertEqual(len(outliers), 1)
        # self.assertEqual(tuple(outliers), tuple([8]))
        # self.assertEqual(len(unit_cell), 2)

    def test_small_2d_cell_vacuum_direction_included(self):
        """Test that the classification can properly handle systems where
        initially three basis vectors are detected, they are reduced to two due
        to wrong dimensionality of the cell, and then although only one
        repetition of the cell is found, it is accepted because its size is
        below the threshold MAX_SINGLE_CELL_SIZE.
        """
        system = get_atoms_from_viz("./structures/BN.json")
        # view(system)

        classifier = Classifier()
        classification = classifier.classify(system)
        self.assertIsInstance(classification, Material2D)

        # No defects or unknown atoms
        adsorbates = classification.adsorbates
        interstitials = classification.interstitials
        substitutions = classification.substitutions
        vacancies = classification.vacancies
        unknowns = classification.unknowns
        self.assertEqual(len(interstitials), 0)
        self.assertEqual(len(substitutions), 0)
        self.assertEqual(len(vacancies), 0)
        self.assertEqual(len(adsorbates), 0)
        self.assertEqual(len(unknowns), 0)

    def test_vacuum_in_2d_unit_cell(self):
        """Structure where a 2D unit cell is found, but it has a vacuum gap.
        Should be detected by using TSA on the cell.
        """
        system = get_atoms_from_viz("./structures/C12H8+H2N2.json")

        classifier = Classifier()
        classification = classifier.classify(system)
        self.assertEqual(type(classification), Class2D)

    def test_graphene_sheets_close(self):
        """2D materials with a relatively small vacuum gap should be correctly
        identified. If a proper check is not done on the connectivity of the
        unit cell, these kind of structures may get classified as surfaces if
        the maximum cell size is bigger than the vacuum gap.
        """
        system = Material2DTests.graphene.repeat([3, 3, 1])
        old_cell = system.get_cell()
        old_cell[2, 2] = 10
        system.set_cell(old_cell)
        system.center()
        system.set_pbc([True, True, True])
        # view(system)

        classifier = Classifier(max_cell_size=12)
        classification = classifier.classify(system)
        self.assertEqual(type(classification), Material2D)

        # No defects or unknown atoms
        adsorbates = classification.adsorbates
        interstitials = classification.interstitials
        substitutions = classification.substitutions
        vacancies = classification.vacancies
        unknowns = classification.unknowns
        self.assertEqual(len(interstitials), 0)
        self.assertEqual(len(substitutions), 0)
        self.assertEqual(len(vacancies), 0)
        self.assertEqual(len(adsorbates), 0)
        self.assertEqual(len(unknowns), 0)

    def test_too_big_single_cell(self):
        """Test that with when only the simulation cell itself is the found
        unit cell, but the cell size is above a threshold value, the system
        cannot be classified.
        """
        system = Material2DTests.graphene.repeat([3, 3, 1])
        system.set_pbc([True, True, True])

        rng = RandomState(8)
        systax.geometry.make_random_displacement(system, 2, rng)

        # view(system)

        classifier = Classifier()
        classification = classifier.classify(system)
        self.assertIsInstance(classification, Class2D)

    def test_seed_not_in_cell(self):
        """In this case the seed atom is not in the cells when creating
        the prototype cell. If the seed atom is directly at the cell border, it
        might not be found. This tests that the code forces the seed atom to be
        found correctly.
        """
        with open("./structures/PKPif9Fqbl30oVX-710UwCHGMd83y.json", "r") as fin:
            data = json.load(fin)

        section_system = data["sections"]["section_run-0"]["sections"]["section_system-0"]

        system = Atoms(
            positions=1e10*np.array(section_system["atom_positions"]),
            cell=1e10*np.array(section_system["simulation_cell"]),
            symbols=section_system["atom_labels"],
            pbc=True,
        )
        # view(system)

        classifier = Classifier()
        classification = classifier.classify(system)
        self.assertIsInstance(classification, Material2D)

    def test_layered_2d(self):
        """A stacked two-dimensional material. One of the materials should be
        recognized and the other recognized as adsorbate.
        """
        with open("./structures/mat2d_4.json", "r") as fin:
            data = json.load(fin)
        system = Atoms(
            scaled_positions=data["positions"],
            cell=1e10*np.array(data["normalizedCell"]),
            symbols=data["labels"],
            pbc=True,
        )

        classifier = Classifier()
        classification = classifier.classify(system)
        self.assertEqual(type(classification), Material2D)

        # Boron nitrate adsorbate
        adsorbates = classification.adsorbates
        interstitials = classification.interstitials
        substitutions = classification.substitutions
        vacancies = classification.vacancies
        unknowns = classification.unknowns
        self.assertEqual(len(interstitials), 0)
        self.assertEqual(len(substitutions), 0)
        self.assertEqual(len(vacancies), 0)
        self.assertEqual(len(adsorbates), 4)
        self.assertEqual(len(unknowns), 0)
        self.assertEqual(set(adsorbates), set([8, 9, 10, 11]))

    def test_graphene_primitive(self):
        sys = Material2DTests.graphene
        # view(sys)
        classifier = Classifier()
        classification = classifier.classify(sys)
        self.assertIsInstance(classification, Material2D)

        # No defects or unknown atoms
        adsorbates = classification.adsorbates
        interstitials = classification.interstitials
        substitutions = classification.substitutions
        vacancies = classification.vacancies
        unknowns = classification.unknowns
        self.assertEqual(len(interstitials), 0)
        self.assertEqual(len(substitutions), 0)
        self.assertEqual(len(vacancies), 0)
        self.assertEqual(len(adsorbates), 0)
        self.assertEqual(len(unknowns), 0)

    def test_graphene_supercell(self):
        sys = Material2DTests.graphene.repeat([5, 5, 1])
        classifier = Classifier()
        classification = classifier.classify(sys)
        self.assertIsInstance(classification, Material2D)

        # No defects or unknown atoms
        adsorbates = classification.adsorbates
        interstitials = classification.interstitials
        substitutions = classification.substitutions
        vacancies = classification.vacancies
        unknowns = classification.unknowns
        self.assertEqual(len(interstitials), 0)
        self.assertEqual(len(substitutions), 0)
        self.assertEqual(len(vacancies), 0)
        self.assertEqual(len(adsorbates), 0)
        self.assertEqual(len(unknowns), 0)

    def test_graphene_partial_pbc(self):
        sys = Material2DTests.graphene.copy()
        sys.set_pbc([True, True, False])
        classifier = Classifier()
        classification = classifier.classify(sys)
        self.assertIsInstance(classification, Material2D)

        # No defects or unknown atoms
        adsorbates = classification.adsorbates
        interstitials = classification.interstitials
        substitutions = classification.substitutions
        vacancies = classification.vacancies
        unknowns = classification.unknowns
        self.assertEqual(len(interstitials), 0)
        self.assertEqual(len(substitutions), 0)
        self.assertEqual(len(vacancies), 0)
        self.assertEqual(len(adsorbates), 0)
        self.assertEqual(len(unknowns), 0)

    def test_graphene_missing_atom(self):
        """Test graphene with a vacancy defect.
        """
        sys = Material2DTests.graphene.repeat([5, 5, 1])
        del sys[24]
        # view(sys)
        sys.set_pbc([True, True, False])
        classifier = Classifier()
        classification = classifier.classify(sys)
        self.assertIsInstance(classification, Material2D)

        # One vacancy
        adsorbates = classification.adsorbates
        interstitials = classification.interstitials
        substitutions = classification.substitutions
        vacancies = classification.vacancies
        unknowns = classification.unknowns
        self.assertEqual(len(interstitials), 0)
        self.assertEqual(len(substitutions), 0)
        self.assertEqual(len(vacancies), 1)
        self.assertEqual(len(adsorbates), 0)
        self.assertEqual(len(unknowns), 0)

    def test_graphene_substitution(self):
        """Test graphene with a substitution defect.
        """
        sys = Material2DTests.graphene.repeat([5, 5, 1])
        sys[0].number = 7
        # view(sys)
        sys.set_pbc([True, True, False])
        classifier = Classifier()
        classification = classifier.classify(sys)
        self.assertIsInstance(classification, Material2D)

        # One substitution
        adsorbates = classification.adsorbates
        interstitials = classification.interstitials
        substitutions = classification.substitutions
        vacancies = classification.vacancies
        unknowns = classification.unknowns

        self.assertEqual(len(interstitials), 0)
        self.assertEqual(len(substitutions), 1)
        self.assertEqual(len(vacancies), 0)
        self.assertEqual(len(adsorbates), 0)
        self.assertEqual(len(unknowns), 0)

        # Check substitution info
        subst = substitutions[0]
        index = subst.index
        orig_num = subst.original_element
        subst_num = subst.substitutional_element
        self.assertEqual(index, 0)
        self.assertEqual(orig_num, 6)
        self.assertEqual(subst_num, 7)

    def test_graphene_missing_atom_exciting(self):
        """Test a more realistic graphene with a vacancy defect from the
        exciting data in the NOMAD Archive.
        """
        positions = np.array([[0.0, 0.0, 0.0],
            [0.0, 9.833294145128265E-10, 0.0],
            [2.134121238221869E-10, -1.23213547309968E-10, 0.0],
            [2.8283321482383327E-10, 9.83786883934224E-10, 0.0],
            [7.159944277047908E-11, 1.2149852888233143E-10, 0.0],
            [9.239798421116619E-10, 3.6970883192833546E-10, 0.0],
            [7.159944277047908E-11, 8.618308856304952E-10, 0.0],
            [9.239798421116619E-10, 6.136207055601422E-10, 0.0],
            [2.8283321482383327E-10, -4.573464457464822E-13, 0.0],
            [4.2635394347838356E-10, -2.458942411245288E-10, 0.0],
            [1.0647740633039121E-9, -3.6912488204997373E-10, 0.0],
            [8.52284868807466E-10, 2.4537848124459853E-10, 0.0],
            [1.0647740633039121E-9, 1.2269778743003765E-10, 0.0],
            [8.52284868807466E-10, -4.918055758645343E-10, 0.0],
            [4.2635394347838356E-10, -5.328534954072828E-13, 0.0],
            [4.970111804163183E-10, 8.604516522176773E-10, 0.0],
            [7.132179717248617E-11, 3.686497656226703E-10, 0.0],
            [7.100794156171322E-10, 2.4589288839236865E-10, 0.0],
            [7.132179717248617E-11, 6.146797718658073E-10, 0.0],
            [7.100794156171322E-10, 7.374366490961087E-10, 0.0],
            [4.970111804163183E-10, 1.2287788527080025E-10, 0.0],
            [6.39163064087745E-10, 8.6063580825492E-10, 0.0],
            [8.637153048417516E-14, 4.916647072564134E-10, 0.0],
            [6.39163064087745E-10, 1.2269360625790666E-10, 0.0],
            [2.1331073578640276E-10, 1.2303793808046385E-10, 0.0],
            [8.517910281331687E-10, 4.916647072564134E-10, 0.0],
            [2.1331073578640276E-10, 8.602914764323629E-10, 0.0],
            [4.970778494398485E-10, -1.232134858221425E-10, 0.0],
            [9.231674598249378E-10, -3.6921643742207865E-10, 0.0],
            [9.231675663249753E-10, 1.227894042899681E-10, 0.0],
            [2.84056580755611E-10, 2.4557345913912146E-10, 0.0],
            [7.102992316947146E-10, 4.916647687442388E-10, 0.0],
            [2.84056580755611E-10, 7.377560783493561E-10, 0.0],
            [6.391754180921053E-10, -1.2321354730996796E-10, 0.0],
            [8.521187287488282E-10, -2.461564252122759E-10, 0.0],
            [8.521187287488282E-10, -2.706694076601711E-13, 0.0],
            [7.101400141385201E-10, -2.4618501705111326E-10, 0.0],
            [9.231328473127216E-10, -1.23213547309968E-10, 0.0],
            [7.101400141385201E-10, -2.4207756882281025E-13, 0.0],
            [2.84140396285193E-10, 4.916647687442387E-10, 0.0],
            [4.971359984603718E-10, 3.6869170031963166E-10, 0.0],
            [4.971361049604094E-10, 6.146377756810205E-10, 0.0],
            [2.1311743821817984E-10, 3.6878393205781663E-10, 0.0],
            [6.390654035532765E-10, 3.6862443263858213E-10, 0.0],
            [4.262295514344803E-10, 7.375859415363175E-10, 0.0],
            [6.390654035532765E-10, 6.147051048498954E-10, 0.0],
            [4.262295514344803E-10, 2.4574359595216E-10, 0.0],
            [2.1311743821817984E-10, 6.145456054306609E-10, 0.0],
            [4.2613753540200396E-10, 4.916647687442388E-10, 0.0]
        ])
        labels = ["C", "C", "C", "C", "C", "C", "C", "C", "C", "C", "C", "C", "C", "C", "C", "C", "C", "C", "C", "C", "C", "C", "C", "C", "C", "C", "C", "C", "C", "C", "C", "C", "C", "C", "C", "C", "C", "C", "C", "C", "C", "C", "C", "C", "C", "C", "C", "C", "C"]
        cell = np.array([
            [1.0650003758837873E-9, -6.148782545663813E-10, 0.0],
            [0.0, 1.2297565091327626E-9, 0.0],
            [0.0, 0.0, 2.0000003945832858E-9]
        ])
        pbc = True

        system = ase.Atoms(
            positions=1e10*positions,
            symbols=labels,
            cell=1e10*cell,
            pbc=pbc,
        )
        # view(system)

        classifier = Classifier()
        classification = classifier.classify(system)
        self.assertIsInstance(classification, Material2D)
        # view(classification.region.recreate_valid())

        # One vacancy
        adsorbates = classification.adsorbates
        interstitials = classification.interstitials
        substitutions = classification.substitutions
        vacancies = classification.vacancies
        unknowns = classification.unknowns
        self.assertEqual(len(interstitials), 0)
        self.assertEqual(len(substitutions), 0)
        self.assertEqual(len(vacancies), 1)
        self.assertEqual(len(adsorbates), 0)
        self.assertEqual(len(unknowns), 0)

        # Check vacancy position
        vac_atom = vacancies[0]
        vac_symbol = vac_atom.symbol
        vac_pos = vac_atom.position
        self.assertEqual(vac_symbol, "C")
        self.assertTrue(np.allclose(vac_pos, [0.7123, 11.0639, 0], atol=0.05))

    def test_graphene_shaken(self):
        """Test graphene that has randomly oriented but uniform length
        dislocations.
        """
        # Run multiple times with random displacements
        rng = RandomState(7)
        for i in range(15):
            system = Material2DTests.graphene.repeat([5, 5, 1])
            systax.geometry.make_random_displacement(system, 0.1, rng)
            classifier = Classifier()
            classification = classifier.classify(system)
            self.assertIsInstance(classification, Material2D)

            # Pristine
            adsorbates = classification.adsorbates
            interstitials = classification.interstitials
            substitutions = classification.substitutions
            vacancies = classification.vacancies
            unknowns = classification.unknowns
            if len(vacancies) != 0:
                view(system)
                view(classification.region.cell)
            self.assertEqual(len(interstitials), 0)
            self.assertEqual(len(substitutions), 0)
            self.assertEqual(len(vacancies), 0)
            self.assertEqual(len(adsorbates), 0)
            self.assertEqual(len(unknowns), 0)

    def test_chemisorption(self):
        """Test the adsorption where there is sufficient distance between the
        adsorbate and the surface to distinguish between them even if they
        share the same elements.
        """
        with open("./structures/mat2d_adsorbate_unknown.json", "r") as fin:
            data = json.load(fin)
        system = Atoms(
            scaled_positions=data["positions"],
            cell=1e10*np.array(data["normalizedCell"]),
            symbols=data["labels"],
            pbc=True,
        )
        # view(system)

        classifier = Classifier()
        classification = classifier.classify(system)
        self.assertIsInstance(classification, Material2D)

        # No defects or unknown atoms, one adsorbate cluster
        adsorbates = classification.adsorbates
        interstitials = classification.interstitials
        substitutions = classification.substitutions
        vacancies = classification.vacancies
        unknowns = classification.unknowns

        self.assertEqual(len(interstitials), 0)
        self.assertEqual(len(substitutions), 0)
        self.assertEqual(len(vacancies), 0)
        self.assertEqual(len(unknowns), 0)
        self.assertEqual(len(adsorbates), 24)
        self.assertTrue(np.array_equal(adsorbates, np.arange(50, 74)))

    def test_curved_2d(self):
        """Curved 2D-material
        """
        graphene = Atoms(
            symbols=[6, 6],
            cell=np.array((
                [2.4595121467478055, 0.0, 0.0],
                [-1.2297560733739028, 2.13, 0.0],
                [0.0, 0.0, 20.0]
            )),
            scaled_positions=np.array((
                [0.3333333333333333, 0.6666666666666666, 0.5],
                [0.6666666666666667, 0.33333333333333337, 0.5]
            )),
            pbc=True
        )
        graphene = graphene.repeat([5, 5, 1])

        # Bulge the surface
        cell_width = np.linalg.norm(graphene.get_cell()[0, :])
        for atom in graphene:
            pos = atom.position
            distortion_z = 0.4*np.sin(pos[0]/cell_width*2.0*np.pi)
            pos += np.array((0, 0, distortion_z))
        # view(graphene)

        classifier = Classifier()
        classification = classifier.classify(graphene)
        self.assertIsInstance(classification, Material2D)

    def test_mos2_pristine_supercell(self):
        system = ase.build.mx2(
            formula="MoS2",
            kind="2H",
            a=3.18,
            thickness=3.19,
            size=(5, 5, 1),
            vacuum=8)
        system.set_pbc(True)
        # view(system)

        classifier = Classifier()
        classification = classifier.classify(system)
        self.assertIsInstance(classification, Material2D)

        # Pristine
        adsorbates = classification.adsorbates
        interstitials = classification.interstitials
        substitutions = classification.substitutions
        vacancies = classification.vacancies
        unknowns = classification.unknowns
        self.assertEqual(len(interstitials), 0)
        self.assertEqual(len(substitutions), 0)
        self.assertEqual(len(vacancies), 0)
        self.assertEqual(len(adsorbates), 0)
        self.assertEqual(len(unknowns), 0)

    def test_mos2_pristine_primitive(self):
        system = ase.build.mx2(
            formula="MoS2",
            kind="2H",
            a=3.18,
            thickness=3.19,
            size=(1, 1, 1),
            vacuum=8)
        system.set_pbc(True)
        # view(system)

        classifier = Classifier()
        classification = classifier.classify(system)
        self.assertIsInstance(classification, Material2D)

        # Pristine
        adsorbates = classification.adsorbates
        interstitials = classification.interstitials
        substitutions = classification.substitutions
        vacancies = classification.vacancies
        unknowns = classification.unknowns
        self.assertEqual(len(interstitials), 0)
        self.assertEqual(len(substitutions), 0)
        self.assertEqual(len(vacancies), 0)
        self.assertEqual(len(adsorbates), 0)
        self.assertEqual(len(unknowns), 0)

    def test_mos2_substitution(self):
        system = ase.build.mx2(
            formula="MoS2",
            kind="2H",
            a=3.18,
            thickness=3.19,
            size=(5, 5, 1),
            vacuum=8)
        system.set_pbc(True)

        symbols = system.get_atomic_numbers()
        symbols[25] = 6
        system.set_atomic_numbers(symbols)

        # view(system)

        classifier = Classifier()
        classification = classifier.classify(system)
        self.assertIsInstance(classification, Material2D)

        # One substitution
        adsorbates = classification.adsorbates
        interstitials = classification.interstitials
        substitutions = classification.substitutions
        vacancies = classification.vacancies
        unknowns = classification.unknowns
        self.assertEqual(len(interstitials), 0)
        self.assertEqual(len(vacancies), 0)
        self.assertEqual(len(adsorbates), 0)
        self.assertEqual(len(unknowns), 0)
        self.assertEqual(len(substitutions), 1)

    def test_mos2_vacancy(self):
        system = ase.build.mx2(
            formula="MoS2",
            kind="2H",
            a=3.18,
            thickness=3.19,
            size=(5, 5, 1),
            vacuum=8)
        system.set_pbc(True)

        del system[25]
        # view(system)

        classifier = Classifier()
        classification = classifier.classify(system)
        self.assertIsInstance(classification, Material2D)

        # One vacancy
        adsorbates = classification.adsorbates
        interstitials = classification.interstitials
        substitutions = classification.substitutions
        vacancies = classification.vacancies
        unknowns = classification.unknowns
        self.assertEqual(len(interstitials), 0)
        self.assertEqual(len(adsorbates), 0)
        self.assertEqual(len(substitutions), 0)
        self.assertEqual(len(unknowns), 0)
        self.assertEqual(len(vacancies), 1)

    def test_mos2_adsorption(self):
        """Test adsorption on mos2 surface.
        """
        system = ase.build.mx2(
            formula="MoS2",
            kind="2H",
            a=3.18,
            thickness=3.19,
            size=(5, 5, 1),
            vacuum=8)
        system.set_pbc(True)

        ads = molecule("C6H6")
        ads.translate([4.9, 5.5, 13])
        system += ads

        # view(system)

        classifier = Classifier()
        classification = classifier.classify(system)
        self.assertIsInstance(classification, Material2D)

        # One adsorbate
        adsorbates = classification.adsorbates
        interstitials = classification.interstitials
        substitutions = classification.substitutions
        vacancies = classification.vacancies
        unknowns = classification.unknowns
        self.assertEqual(len(interstitials), 0)
        self.assertEqual(len(substitutions), 0)
        self.assertEqual(len(unknowns), 0)
        self.assertEqual(len(vacancies), 0)
        self.assertEqual(len(adsorbates), 12)
        self.assertTrue(np.array_equal(adsorbates, range(75, 87)))

    def test_2d_split(self):
        """A simple 2D system where the system has been split by the cell
        boundary.
        """
        system = Atoms(
            symbols=["H", "C"],
            cell=np.array((
                [2, 0.0, 0.0],
                [0.0, 2, 0.0],
                [0.0, 0.0, 15]
            )),
            positions=np.array((
                [0, 0, 0],
                [0, 0, 13.8],
            )),
            pbc=True
        )
        # view(system)
        classifier = Classifier()
        classification = classifier.classify(system)
        self.assertIsInstance(classification, Material2D)

        # Pristine
        basis = classification.basis_indices
        adsorbates = classification.adsorbates
        interstitials = classification.interstitials
        substitutions = classification.substitutions
        vacancies = classification.vacancies
        unknowns = classification.unknowns
        self.assertEqual(len(interstitials), 0)
        self.assertEqual(len(substitutions), 0)
        self.assertEqual(len(unknowns), 0)
        self.assertEqual(len(vacancies), 0)
        self.assertEqual(len(adsorbates), 0)
        self.assertEqual(set(basis), set(range(len(system))))

    def test_graphene_rectangular(self):
        system = Atoms(
            symbols=["C", "C", "C", "C"],
            cell=np.array((
                [4.26, 0.0, 0.0],
                [0.0, 15, 0.0],
                [0.0, 0.0, 2.4595121467478055]
            )),
            positions=np.array((
                [2.84, 7.5, 6.148780366869514e-1],
                [3.55, 7.5, 1.8446341100608543],
                [7.1e-1, 7.5, 1.8446341100608543],
                [1.42, 7.5, 6.148780366869514e-1],
            )),
            pbc=True
        )
        # view(system)
        classifier = Classifier()
        classification = classifier.classify(system)
        self.assertIsInstance(classification, Material2D)

        # Pristine
        basis = classification.basis_indices
        adsorbates = classification.adsorbates
        interstitials = classification.interstitials
        substitutions = classification.substitutions
        vacancies = classification.vacancies
        unknowns = classification.unknowns
        self.assertEqual(len(interstitials), 0)
        self.assertEqual(len(substitutions), 0)
        self.assertEqual(len(unknowns), 0)
        self.assertEqual(len(vacancies), 0)
        self.assertEqual(len(adsorbates), 0)
        self.assertEqual(set(basis), set(range(len(system))))

    def test_boron_nitride(self):
        system = Atoms(
            symbols=["B", "N"],
            cell=np.array((
                [2.412000008147063, 0.0, 0.0],
                [-1.2060000067194177, 2.0888532824002019, 0.0],
                [0.0, 0.0, 15.875316320100001]
            )),
            positions=np.array((
                [0, 0, 0],
                [-1.3823924100453746E-9, 1.3925688618963122, 0.0]
            )),
            pbc=True
        )
        # view(system)
        classifier = Classifier()
        classification = classifier.classify(system)
        self.assertIsInstance(classification, Material2D)

        # Pristine
        basis = classification.basis_indices
        adsorbates = classification.adsorbates
        interstitials = classification.interstitials
        substitutions = classification.substitutions
        vacancies = classification.vacancies
        unknowns = classification.unknowns
        self.assertEqual(len(interstitials), 0)
        self.assertEqual(len(substitutions), 0)
        self.assertEqual(len(unknowns), 0)
        self.assertEqual(len(vacancies), 0)
        self.assertEqual(len(adsorbates), 0)
        self.assertEqual(set(basis), set(range(len(system))))

    def test_fluorographene(self):
        system = Atoms(
            scaled_positions=np.array([
                [1.3012393333576103e-06, 0.9999449352451434, 0.07686917114285712],
                [0.666645333381887, 0.9999840320410395, 0.10381504828571426],
                [0.16664461721471663, 0.49999686527625936, 0.10381366714285713],
                [0.5000035589866841, 0.49995279413001426, 0.07686989028571428],
                [0.9999651360110703, 6.476326633588427e-05, 0.0026979231428571424],
                [0.6665936880181591, 6.312126818602304e-05, 0.17797979399999994],
                [0.16658826335530388, 0.5001281031872844, 0.1779785431428571],
                [0.49997811077528137, 0.5001300794718694, 0.002698536571428571]
            ]),
            cell=np.array([
                [4.359520614662661, 0.0, 0.0],
                [0.0, 2.516978484830788, 0.0],
                [0.0, 0.0, 18.521202373450003]
            ]),
            symbols=[6, 6, 6, 6, 9, 9, 9, 9],
            pbc=True
        )

        classifier = Classifier()
        classification = classifier.classify(system)
        self.assertIsInstance(classification, Material2D)

        # Pristine
        adsorbates = classification.adsorbates
        interstitials = classification.interstitials
        substitutions = classification.substitutions
        vacancies = classification.vacancies
        unknowns = classification.unknowns
        self.assertEqual(len(interstitials), 0)
        self.assertEqual(len(substitutions), 0)
        self.assertEqual(len(vacancies), 0)
        self.assertEqual(len(adsorbates), 0)
        self.assertEqual(len(unknowns), 0)


class Material3DTests(unittest.TestCase):
    """Tests detection of bulk 3D materials.
    """
    def test_thin_sparse(self):
        """Test a crystal that is very thin.
        """
        system = Atoms(
            scaled_positions=np.array([
                [0.875000071090061, 0.6250000710900608, 0.2499998578198783],
                [0.12499992890993901, 0.37499992890993905, 0.750000142180122],
                [0.624999928909939, 0.8749999289099393, 0.750000142180122],
                [0.37500007109006084, 0.12500007109006087, 0.2499998578198783]
            ]),
            symbols=[5, 5, 51, 51],
            cell=np.array([
                [10.1, 0.0, 0.0],
                [0.0, 10.1, 0.0],
                [5.05, 5.05, 1.758333]
            ]),
            pbc=[True, True, True],
        )

        classifier = Classifier()
        classification = classifier.classify(system)
        self.assertIsInstance(classification, Crystal)

    def test_si(self):
        si = ase.lattice.cubic.Diamond(
            size=(1, 1, 1),
            symbol='Si',
            pbc=(1, 1, 1),
            latticeconstant=5.430710)
        classifier = Classifier()
        clas = classifier.classify(si)
        self.assertIsInstance(clas, Crystal)

    def test_si_shaken(self):
        rng = RandomState(47)
        for i in range(10):
            si = ase.lattice.cubic.Diamond(
                size=(1, 1, 1),
                symbol='Si',
                pbc=(1, 1, 1),
                latticeconstant=5.430710)
            systax.geometry.make_random_displacement(si, 0.2, rng)
            classifier = Classifier()
            clas = classifier.classify(si)
            self.assertIsInstance(clas, Crystal)

    def test_graphite(self):
        """Testing a sparse material like graphite.
        """
        sys = ase.lattice.hexagonal.Graphite(
            size=(1, 1, 1),
            symbol='C',
            pbc=(1, 1, 1),
            latticeconstant=(2.461, 6.708))
        classifier = Classifier()
        clas = classifier.classify(sys)
        self.assertIsInstance(clas, Crystal)

    def test_amorphous(self):
        """Test an amorphous crystal with completely random positions. This is
        currently not classified as crystal, but the threshold can be set in
        the classifier setup.
        """
        n_atoms = 50
        rng = RandomState(8)
        rand_pos = rng.rand(n_atoms, 3)

        sys = Atoms(
            scaled_positions=rand_pos,
            cell=(10, 10, 10),
            symbols=n_atoms*['C'],
            pbc=(1, 1, 1))
        classifier = Classifier()
        clas = classifier.classify(sys)
        self.assertIsInstance(clas, Class3D)

    def test_too_sparse(self):
        """Test a crystal that is too sparse.
        """
        sys = ase.lattice.hexagonal.Graphite(
            size=(1, 1, 1),
            symbol='C',
            pbc=(1, 1, 1),
            latticeconstant=(2.461, 12))

        classifier = Classifier()
        clas = classifier.classify(sys)
        self.assertIsInstance(clas, Unknown)


class SurfaceTests(unittest.TestCase):
    """Tests for detecting and analyzing surfaces.
    """
    def test_2d_motif_in_surface_hard(self):
        """Test that if a 2D substructure is found within a surface, and the 2D
        substructure covers a lot of the structure, the entire structure is
        still not classified according to that motif if it does not wrap to
        itself in the two basis vector directions.
        """
        translation = np.array([0, 0, 2])
        n_rep = 3
        graphene = Material2DTests.graphene.repeat((n_rep, n_rep, 1))
        layer1 = graphene

        layer2 = graphene.copy()
        layer2.set_chemical_symbols(["O"]*len(layer2))
        rng = RandomState(47)
        systax.geometry.make_random_displacement(layer2, 1, rng)
        layer2.translate(translation)

        system = layer1 + layer2

        old_cell = system.get_cell()
        old_cell[0, :] *= 2
        old_cell[2, :] = np.array([0, 0, 4])
        system.set_cell(old_cell)
        system.center()
        # view(system)

        # Should be classified as Class2D because the 2D motif that is detected
        # is not really periodic in the found basis vector directions (does not
        # wrap to itself).
        classifier = Classifier(max_cell_size=3, pos_tol=0.25)
        classification = classifier.classify(system)
        self.assertEqual(type(classification), Class2D)

    def test_2d_motif_in_surface_easy(self):
        """Test that if a 2D substructure is found within a surface, the entire
        structure is not classified according to that motif if it does not
        cover enough of the structure.
        """
        # Here we create a 2D system which has alternating layers of ordered
        # and disordered sheets of 2D materials, but rotated 90 degree with
        # respect to the surface plane.
        translation = np.array([0, 0, 2])
        n_rep = 3
        graphene = Material2DTests.graphene.repeat((n_rep, n_rep, 1))
        layer1 = graphene

        layer2 = graphene.copy()
        layer2.set_chemical_symbols(["O"]*len(layer2))
        rng = RandomState(47)
        systax.geometry.make_random_displacement(layer2, 1, rng)
        layer2.translate(translation)

        layer3 = layer1.copy()
        layer3.translate(2*translation)

        layer4 = graphene.copy()
        layer4.set_chemical_symbols(["N"]*len(layer2))
        rng = RandomState(47)
        systax.geometry.make_random_displacement(layer4, 1, rng)
        layer4.translate(3*translation)

        system = layer1 + layer2 + layer3 + layer4

        old_cell = system.get_cell()
        old_cell[0, :] *= 3
        old_cell[2, :] = np.array([0, 0, 8])
        system.set_cell(old_cell)
        system.center()
        # view(system)

        # Should be classified as Class2D because the coverage is too small
        classifier = Classifier(max_cell_size=4)
        classification = classifier.classify(system)
        self.assertEqual(type(classification), Class2D)

    def test_surface_difficult_basis_atoms(self):
        """This is a surface where the atoms on top of the surface will get
        easily classified as adsorbates if the chemical environment detection
        is not tuned correctly.
        """
        system = get_atoms_from_viz("./structures/O24Sr8Ti12.json")
        # view(system)

        # With a little higher chemical similarity threshold the whole surface
        # is not detected
        classifier = Classifier(chem_similarity_threshold=0.45)
        classification = classifier.classify(system)
        self.assertIsInstance(classification, Surface)

        # Has outliers with these settings
        outliers = classification.outliers
        self.assertTrue(len(outliers) != 0)

        # With a little lower chemical similarity threshold the whole surface
        # is again detected
        classifier = Classifier(chem_similarity_threshold=0.40)
        classification = classifier.classify(system)
        self.assertIsInstance(classification, Surface)

        # Has outliers with these settings
        outliers = classification.outliers
        self.assertTrue(len(outliers) == 0)

    # def test_surface_with_one_cell_but_periodic_backbone(self):
        # """This is a surface that ultimately has only one repetition of the
        # underlying unit cell in the simulation cell. Normally it would not get
        # classified, but because it has a periodic backbone of Barium atoms,
        # they are identified as the unit cell and everything inside is
        # identified as outliers. Such systems still pose a challenge to the
        # algorithm.
        # """
        # system = get_atoms_from_viz("./structures/Ba16+O40Si12.json")
        # view(system)

        # classifier = Classifier()
        # classification = classifier.classify(system)
        # self.assertIsInstance(classification, Surface)

        # # No outliers
        # outliers = classification.outliers
        # self.assertEqual(len(outliers), 0)

    def test_adsorbate_detection_via_neighbourhood(self):
        """Test that adsorbates that are in a basis atom position, but do not
        exhibit the correct chemical neighbourhood are identified.
        """
        system = get_atoms_from_arch("./structures/Pbsl6Hlb_C1aXadFiJ58UCUek5a8x.json")
        # view(system)

        classifier = Classifier()
        classification = classifier.classify(system)
        self.assertIsInstance(classification, Surface)

        # Only adsorbates
        adsorbates = classification.adsorbates
        interstitials = classification.interstitials
        substitutions = classification.substitutions
        vacancies = classification.vacancies
        unknowns = classification.unknowns

        self.assertEqual(len(interstitials), 0)
        self.assertEqual(len(substitutions), 0)
        self.assertEqual(len(vacancies), 0)
        self.assertEqual(len(adsorbates), 18)
        self.assertEqual(len(unknowns), 0)
        self.assertTrue(np.array_equal(adsorbates, np.arange(0, 18)))

    def test_surface_wrong_cm(self):
        """Test that the seed atom is correctly chosen near the center of mass
        even if the structure is cut.
        """
        system = bcc100('Fe', size=(3, 3, 4), vacuum=8)
        adsorbate = ase.Atom(position=[4, 4, 4], symbol="H")
        system += adsorbate
        system.set_pbc([True, True, True])
        system.translate([0, 0, 10])
        system.wrap()
        # view(system)

        classifier = Classifier()
        classification = classifier.classify(system)
        # view(classification.region.recreate_valid())
        # view(classification.region.cell)
        self.assertIsInstance(classification, Surface)

        # One adsorbate
        adsorbates = classification.adsorbates
        interstitials = classification.interstitials
        substitutions = classification.substitutions
        vacancies = classification.vacancies
        unknowns = classification.unknowns
        self.assertEqual(len(interstitials), 0)
        self.assertEqual(len(substitutions), 0)
        self.assertEqual(len(vacancies), 0)
        self.assertEqual(len(adsorbates), 1)
        self.assertEqual(len(unknowns), 0)

    def test_search_beyond_limits(self):
        """In this system the found unit cell cannot be used to seach the whole
        surface unless seed atoms for unit cells beyond the original simulation
        cell boundaries are not allowed.
        """
        system = get_atoms_from_arch("./structures/PEzXqLISX8Pam-HlJMxeLc86lcKgf.json")

        classifier = Classifier()
        classification = classifier.classify(system)
        self.assertIsInstance(classification, Surface)

        # Only adsorbates
        adsorbates = classification.adsorbates
        interstitials = classification.interstitials
        substitutions = classification.substitutions
        vacancies = classification.vacancies
        unknowns = classification.unknowns
        self.assertEqual(len(vacancies), 0)
        self.assertEqual(len(substitutions), 0)
        self.assertEqual(len(adsorbates), 14)
        self.assertEqual(len(unknowns), 0)
        self.assertEqual(len(interstitials), 0)

    def test_ordered_adsorbates(self):
        """Test surface where on top there are adsorbates with high
        connectivity in two directions. These kind of adsorbates could not be
        detected if the size of the connected components would not be checked.
        """
        system = get_atoms_from_arch("./structures/P8Wnwz4dfyea6UAD0WEBadXv83wyf.json")
        # view(system)

        classifier = Classifier()
        classification = classifier.classify(system)
        self.assertIsInstance(classification, Surface)

        # Only adsorbates
        adsorbates = classification.adsorbates
        interstitials = classification.interstitials
        substitutions = classification.substitutions
        vacancies = classification.vacancies
        unknowns = classification.unknowns

        self.assertEqual(len(interstitials), 0)
        self.assertEqual(len(substitutions), 0)
        self.assertEqual(len(vacancies), 0)
        self.assertEqual(len(adsorbates), 13)
        self.assertEqual(len(unknowns), 0)
        self.assertTrue(np.array_equal(adsorbates, np.arange(0, 13)))

    def test_surface_with_one_basis_vector_as_span(self):
        system = get_atoms_from_viz("./structures/C2H4Ru36.json")
        # view(system)

        classifier = Classifier()
        classification = classifier.classify(system)
        self.assertIsInstance(classification, Surface)

        # view(classification.region.recreate_valid())

        # Only adsorbates
        adsorbates = classification.adsorbates
        interstitials = classification.interstitials
        substitutions = classification.substitutions
        vacancies = classification.vacancies
        unknowns = classification.unknowns
        self.assertEqual(len(interstitials), 0)
        self.assertEqual(len(substitutions), 0)
        self.assertEqual(len(vacancies), 0)
        self.assertEqual(len(adsorbates), 6)
        self.assertEqual(len(unknowns), 0)
        self.assertTrue(np.array_equal(adsorbates, np.arange(0, 6)))

    def test_cut_surface(self):
        """Test a surface that has been cut by the cell boundary. Should still
        be detected as single surface.
        """
        system = get_atoms_from_viz("./structures/Ba20O52Ti20.json")
        # view(system)

        classifier = Classifier()
        classification = classifier.classify(system)
        self.assertIsInstance(classification, Surface)

        # Pristine
        adsorbates = classification.adsorbates
        interstitials = classification.interstitials
        substitutions = classification.substitutions
        vacancies = classification.vacancies
        unknowns = classification.unknowns

        self.assertEqual(len(interstitials), 0)
        self.assertEqual(len(substitutions), 0)
        self.assertEqual(len(vacancies), 0)
        self.assertEqual(len(adsorbates), 0)
        self.assertEqual(len(unknowns), 0)

    def test_zinc_blende(self):
        system = Zincblende(symbol=["Au", "Fe"], latticeconstant=5)
        system = system.repeat((4, 4, 2))
        cell = system.get_cell()
        cell[2, :] *= 3
        system.set_cell(cell)
        system.center()
        # view(system)

        classifier = Classifier()
        classification = classifier.classify(system)
        self.assertIsInstance(classification, Surface)

        # Check that the right cell is found
        analyzer = classification.cell_analyzer
        space_group = analyzer.get_space_group_number()
        self.assertEqual(space_group, 216)

        # No defects or unknown atoms
        adsorbates = classification.adsorbates
        interstitials = classification.interstitials
        substitutions = classification.substitutions
        vacancies = classification.vacancies
        unknowns = classification.unknowns
        self.assertEqual(len(interstitials), 0)
        self.assertEqual(len(substitutions), 0)
        self.assertEqual(len(vacancies), 0)
        self.assertEqual(len(adsorbates), 0)
        self.assertEqual(len(unknowns), 0)

    def test_bcc_pristine_thin_surface(self):
        system = bcc100('Fe', size=(3, 3, 3), vacuum=8)
        # view(system)
        classifier = Classifier()
        classification = classifier.classify(system)
        self.assertIsInstance(classification, Surface)

        # No defects or unknown atoms
        adsorbates = classification.adsorbates
        interstitials = classification.interstitials
        substitutions = classification.substitutions
        vacancies = classification.vacancies
        unknowns = classification.unknowns
        self.assertEqual(len(interstitials), 0)
        self.assertEqual(len(substitutions), 0)
        self.assertEqual(len(vacancies), 0)
        self.assertEqual(len(adsorbates), 0)
        self.assertEqual(len(unknowns), 0)

    def test_bcc_pristine_small_surface(self):
        system = bcc100('Fe', size=(1, 1, 3), vacuum=8)
        # view(system)
        classifier = Classifier()
        classification = classifier.classify(system)
        self.assertIsInstance(classification, Surface)

        # No defects or unknown atoms
        adsorbates = classification.adsorbates
        interstitials = classification.interstitials
        substitutions = classification.substitutions
        vacancies = classification.vacancies
        unknowns = classification.unknowns
        self.assertEqual(len(interstitials), 0)
        self.assertEqual(len(substitutions), 0)
        self.assertEqual(len(vacancies), 0)
        self.assertEqual(len(adsorbates), 0)
        self.assertEqual(len(unknowns), 0)

    def test_bcc_pristine_big_surface(self):
        system = bcc100('Fe', size=(5, 5, 3), vacuum=8)
        # view(system)
        classifier = Classifier()
        classification = classifier.classify(system)
        self.assertIsInstance(classification, Surface)

        # No defects or unknown atoms
        adsorbates = classification.adsorbates
        interstitials = classification.interstitials
        substitutions = classification.substitutions
        vacancies = classification.vacancies
        unknowns = classification.unknowns
        self.assertEqual(len(interstitials), 0)
        self.assertEqual(len(substitutions), 0)
        self.assertEqual(len(vacancies), 0)
        self.assertEqual(len(adsorbates), 0)
        self.assertEqual(len(unknowns), 0)

    def test_bcc_substitution(self):
        """Surface with substitutional point defect.
        """
        system = bcc100('Fe', size=(5, 5, 3), vacuum=8)
        labels = system.get_atomic_numbers()
        sub_index = 42
        sub_element = 20
        labels[sub_index] = sub_element
        system.set_atomic_numbers(labels)
        # view(system)

        # Classified as surface
        classifier = Classifier()
        classification = classifier.classify(system)
        self.assertIsInstance(classification, Surface)

        # One substitutional defect
        adsorbates = classification.adsorbates
        interstitials = classification.interstitials
        substitutions = classification.substitutions
        vacancies = classification.vacancies
        unknowns = classification.unknowns
        self.assertEqual(len(interstitials), 0)
        self.assertEqual(len(vacancies), 0)
        self.assertEqual(len(adsorbates), 0)
        self.assertEqual(len(unknowns), 0)
        self.assertEqual(len(substitutions), 1)
        subst = substitutions[0]
        self.assertEqual(subst.index, sub_index)
        self.assertEqual(subst.original_element, 26)
        self.assertEqual(subst.substitutional_element, sub_element)

    def test_bcc_vacancy(self):
        """Surface with vacancy point defect.
        """
        system = bcc100('Fe', size=(5, 5, 3), vacuum=8)
        vac_index = 42

        # Get the vacancy atom
        vac_true = ase.Atom(
            system[vac_index].symbol,
            system[vac_index].position,
        )
        del system[vac_index]
        # view(system)

        # Classified as surface
        classifier = Classifier()
        classification = classifier.classify(system)
        self.assertIsInstance(classification, Surface)

        # One vacancy
        adsorbates = classification.adsorbates
        interstitials = classification.interstitials
        substitutions = classification.substitutions
        vacancies = classification.vacancies
        unknowns = classification.unknowns
        self.assertEqual(len(interstitials), 0)
        self.assertEqual(len(adsorbates), 0)
        self.assertEqual(len(unknowns), 0)
        self.assertEqual(len(substitutions), 0)
        self.assertEqual(len(vacancies), 1)
        vac_found = vacancies[0]
        self.assertTrue(np.allclose(vac_true.position, vac_found.position))
        self.assertEqual(vac_true.symbol, vac_found.symbol)

    def test_bcc_interstitional(self):
        """Surface with interstitional atom.
        """
        system = bcc100('Fe', size=(5, 5, 5), vacuum=8)

        # Add an interstitionl atom
        interstitional = ase.Atom(
            "C",
            [8, 8, 9],
        )
        system += interstitional

        # view(system)

        # Classified as surface
        classifier = Classifier()
        classification = classifier.classify(system)
        self.assertIsInstance(classification, Surface)

        # One interstitional
        adsorbates = classification.adsorbates
        interstitials = classification.interstitials
        substitutions = classification.substitutions
        vacancies = classification.vacancies
        unknowns = classification.unknowns
        self.assertEqual(len(vacancies), 0)
        self.assertEqual(len(substitutions), 0)
        self.assertEqual(len(adsorbates), 0)
        self.assertEqual(len(unknowns), 0)
        self.assertEqual(len(interstitials), 1)
        int_found = interstitials[0]
        self.assertEqual(int_found, 125)

    def test_bcc_dislocated_big_surface(self):
        system = bcc100('Fe', size=(5, 5, 3), vacuum=8)

        # Run multiple times with random displacements
        rng = RandomState(47)
        for i in range(10):
            sys = system.copy()
            systax.geometry.make_random_displacement(sys, 0.2, rng)
            # view(sys)

            # Classified as surface
            classifier = Classifier()
            classification = classifier.classify(sys)
            self.assertIsInstance(classification, Surface)

            # No defects or unknown atoms
            adsorbates = classification.adsorbates
            interstitials = classification.interstitials
            substitutions = classification.substitutions
            vacancies = classification.vacancies
            unknowns = classification.unknowns
            # print(unknowns)
            self.assertEqual(len(interstitials), 0)
            self.assertEqual(len(substitutions), 0)
            self.assertEqual(len(vacancies), 0)
            self.assertEqual(len(adsorbates), 0)
            self.assertEqual(len(unknowns), 0)

    def test_curved_surface(self):
        # Create an Fe 100 surface as an ASE Atoms object
        system = bcc100('Fe', size=(12, 12, 3), vacuum=8)

        # Bulge the surface
        cell_width = np.linalg.norm(system.get_cell()[0, :])
        for atom in system:
            pos = atom.position
            distortion_z = 0.5*np.sin(pos[0]/cell_width*2.0*np.pi)
            pos += np.array((0, 0, distortion_z))
        # view(system)

        # Classified as surface
        classifier = Classifier()
        classification = classifier.classify(system)
        self.assertIsInstance(classification, Surface)

        # No defects or unknown atoms
        adsorbates = classification.adsorbates
        interstitials = classification.interstitials
        substitutions = classification.substitutions
        vacancies = classification.vacancies
        unknowns = classification.unknowns
        self.assertEqual(len(interstitials), 0)
        self.assertEqual(len(substitutions), 0)
        self.assertEqual(len(vacancies), 0)
        self.assertEqual(len(adsorbates), 0)
        self.assertEqual(len(unknowns), 0)

    def test_surface_ads(self):
        """Test a surface with an adsorbate.
        """
        # Create an Fe 100 surface as an ASE Atoms object
        system = bcc100('Fe', size=(5, 5, 4), vacuum=8)

        # Add a H2O molecule on top of the surface
        h2o = molecule("H2O")
        h2o.rotate(180, [1, 0, 0])
        h2o.translate([7.2, 7.2, 13.5])
        system += h2o
        # view(system)

        classifier = Classifier()
        classification = classifier.classify(system)
        self.assertIsInstance(classification, Surface)

        # No defects or unknown atoms, one adsorbate cluster
        adsorbates = classification.adsorbates
        interstitials = classification.interstitials
        substitutions = classification.substitutions
        vacancies = classification.vacancies
        unknowns = classification.unknowns

        self.assertEqual(len(interstitials), 0)
        self.assertEqual(len(substitutions), 0)
        self.assertEqual(len(vacancies), 0)
        self.assertEqual(len(unknowns), 0)
        self.assertEqual(len(adsorbates), 3)
        self.assertTrue(np.array_equal(adsorbates, np.array([100, 101, 102])))

    def test_nacl(self):
        """Test the detection for an imperfect NaCl surface with adsorbate and
        defects.
        """
        # Create the system
        class NaClFactory(SimpleCubicFactory):
            "A factory for creating NaCl (B1, Rocksalt) lattices."

            bravais_basis = [[0, 0, 0], [0, 0, 0.5], [0, 0.5, 0], [0, 0.5, 0.5],
                            [0.5, 0, 0], [0.5, 0, 0.5], [0.5, 0.5, 0],
                            [0.5, 0.5, 0.5]]
            element_basis = (0, 1, 1, 0, 1, 0, 0, 1)

        nacl = NaClFactory()
        nacl = nacl(symbol=["Na", "Cl"], latticeconstant=5.64)
        nacl = nacl.repeat((4, 4, 2))
        cell = nacl.get_cell()
        cell[2, :] *= 3
        nacl.set_cell(cell)
        nacl.center()

        # Add vacancy
        vac_index = 17
        vac_true = ase.Atom(
            nacl[vac_index].symbol,
            nacl[vac_index].position,
        )
        del nacl[vac_index]

        # Shake the atoms
        # rng = RandomState(8)
        # systax.geometry.make_random_displacement(nacl, 0.4, rng)

        # Add adsorbate
        h2o = molecule("H2O")
        h2o.rotate(-45, [0, 0, 1])
        h2o.translate([11.5, 11.5, 22.5])
        nacl += h2o

        # Add substitution
        symbols = nacl.get_atomic_numbers()
        subst_num = 39
        subst_atomic_num = 19
        symbols[subst_num] = subst_atomic_num
        nacl.set_atomic_numbers(symbols)

        # view(nacl)

        classifier = Classifier()
        classification = classifier.classify(nacl)
        self.assertIsInstance(classification, Surface)

        # Detect adsorbate
        adsorbates = classification.adsorbates
        # print(adsorbates)
        self.assertEqual(len(adsorbates), 3)
        self.assertTrue(np.array_equal(adsorbates, np.array([256, 257, 255])))

        # Detect vacancy
        vacancies = classification.vacancies
        self.assertEqual(len(vacancies), 1)
        vac_found = vacancies[0]
        vacancy_disp = np.linalg.norm(vac_true.position - vac_found.position)
        self.assertTrue(vacancy_disp <= 1)
        self.assertEqual(vac_true.symbol, vac_found.symbol)

        # Detect substitution
        substitutions = classification.substitutions
        self.assertEqual(len(substitutions), 1)
        found_subst = substitutions[0]
        self.assertEqual(found_subst.index, subst_num)
        self.assertEqual(found_subst.original_element, 11)
        self.assertEqual(found_subst.substitutional_element, subst_atomic_num)

        # No unknown atoms
        unknowns = classification.unknowns
        self.assertEqual(len(unknowns), 0)

        # No interstitials
        interstitials = classification.interstitials
        self.assertEqual(len(interstitials), 0)


class Material3DAnalyserTests(unittest.TestCase):
    """Tests the analysis of bulk 3D materials.
    """
    def test_diamond(self):
        """Test that a silicon diamond lattice is characterized correctly.
        """
        # Create the system
        si = ase.lattice.cubic.Diamond(
            size=(1, 1, 1),
            symbol='Si',
            pbc=(1, 1, 1),
            latticeconstant=5.430710)

        # Apply some noise
        si.rattle(stdev=0.05, seed=42)
        si.translate([1, 2, 1])
        cell = si.get_cell()
        a = cell[0, :]
        a *= 1.04
        cell[0, :] = a
        si.set_cell(cell)

        # Get the data
        data = self.get_material3d_properties(si)

        # Check that the data is valid
        self.assertEqual(data.chiral, False)
        self.assertEqual(data.space_group_number, 227)
        self.assertEqual(data.space_group_int, "Fd-3m")
        self.assertEqual(data.hall_symbol, "F 4d 2 3 -1d")
        self.assertEqual(data.hall_number, 525)
        self.assertEqual(data.point_group, "m-3m")
        self.assertEqual(data.crystal_system, "cubic")
        self.assertEqual(data.bravais_lattice, "cF")
        self.assertEqual(data.choice, "1")
        self.assertTrue(np.array_equal(data.equivalent_conv, [0, 0, 0, 0, 0, 0, 0, 0]))
        self.assertTrue(np.array_equal(data.wyckoff_conv, ["a", "a", "a", "a", "a", "a", "a", "a"]))
        self.assertTrue(np.array_equal(data.equivalent_original, [0, 0, 0, 0, 0, 0, 0, 0]))
        self.assertTrue(np.array_equal(data.wyckoff_original, ["a", "a", "a", "a", "a", "a", "a", "a"]))
        self.assertTrue(np.array_equal(data.prim_wyckoff, ["a", "a"]))
        self.assertTrue(np.array_equal(data.prim_equiv, [0, 0]))
        self.assertFalse(data.has_free_wyckoff_parameters)
        self.assertWyckoffGroupsOk(data.conv_system, data.wyckoff_groups_conv)
        self.assertVolumeOk(si, data.conv_system, data.lattice_fit)

    def test_fcc(self):
        """Test that a primitive NaCl fcc lattice is characterized correctly.
        """
        # Create the system
        cell = np.array(
            [
                [0, 2.8201, 2.8201],
                [2.8201, 0, 2.8201],
                [2.8201, 2.8201, 0]
            ]
        )
        cell[0, :] *= 1.05
        nacl = Atoms(
            symbols=["Na", "Cl"],
            scaled_positions=np.array([
                [0, 0, 0],
                [0.5, 0.5, 0.5]
            ]),
            cell=cell,
        )

        # Get the data
        data = self.get_material3d_properties(nacl)

        # Check that the data is valid
        self.assertEqual(data.space_group_number, 225)
        self.assertEqual(data.space_group_int, "Fm-3m")
        self.assertEqual(data.hall_symbol, "-F 4 2 3")
        self.assertEqual(data.hall_number, 523)
        self.assertEqual(data.point_group, "m-3m")
        self.assertEqual(data.crystal_system, "cubic")
        self.assertEqual(data.bravais_lattice, "cF")
        self.assertEqual(data.choice, "")
        self.assertTrue(np.array_equal(data.equivalent_conv, [0, 1, 0, 1, 0, 1, 0, 1]))
        self.assertTrue(np.array_equal(data.wyckoff_conv, ["a", "b", "a", "b", "a", "b", "a", "b"]))
        self.assertTrue(np.array_equal(data.equivalent_original, [0, 1]))
        self.assertTrue(np.array_equal(data.wyckoff_original, ["a", "b"]))
        self.assertTrue(np.array_equal(data.prim_equiv, [0, 1]))
        self.assertTrue(np.array_equal(data.prim_wyckoff, ["a", "b"]))
        self.assertFalse(data.has_free_wyckoff_parameters)
        self.assertWyckoffGroupsOk(data.conv_system, data.wyckoff_groups_conv)
        self.assertVolumeOk(nacl, data.conv_system, data.lattice_fit)

    def test_bcc(self):
        """Test that a body centered cubic lattice for copper is characterized
        correctly.
        """
        from ase.lattice.cubic import BodyCenteredCubic
        system = BodyCenteredCubic(
            directions=[[1, 0, 0], [0, 1, 0], [1, 1, 1]],
            size=(1, 1, 1),
            symbol='Cu',
            pbc=True,
            latticeconstant=4.0)

        # Get the data
        data = self.get_material3d_properties(system)

        # Check that the data is valid
        self.assertEqual(data.space_group_number, 229)
        self.assertEqual(data.space_group_int, "Im-3m")
        self.assertEqual(data.hall_symbol, "-I 4 2 3")
        self.assertEqual(data.hall_number, 529)
        self.assertEqual(data.point_group, "m-3m")
        self.assertEqual(data.crystal_system, "cubic")
        self.assertEqual(data.bravais_lattice, "cI")
        self.assertEqual(data.choice, "")
        self.assertTrue(np.array_equal(data.equivalent_conv, [0, 0]))
        self.assertTrue(np.array_equal(data.wyckoff_conv, ["a", "a"]))
        self.assertTrue(np.array_equal(data.equivalent_original, [0]))
        self.assertTrue(np.array_equal(data.wyckoff_original, ["a"]))
        self.assertTrue(np.array_equal(data.prim_equiv, [0]))
        self.assertTrue(np.array_equal(data.prim_wyckoff, ["a"]))
        self.assertFalse(data.has_free_wyckoff_parameters)
        self.assertWyckoffGroupsOk(data.conv_system, data.wyckoff_groups_conv)
        self.assertVolumeOk(system, data.conv_system, data.lattice_fit)

    def test_unsymmetric(self):
        """Test that a random system is handled correctly.
        """
        rng = RandomState(42)
        positions = 10*rng.rand(10, 3)
        system = Atoms(
            positions=positions,
            symbols=["H", "C", "Na", "Fe", "Cu", "He", "Ne", "Mg", "Si", "Ti"],
            cell=[10, 10, 10]
        )

        # Get the data
        data = self.get_material3d_properties(system)

        # Check that the data is valid
        self.assertEqual(data.space_group_number, 1)
        self.assertEqual(data.space_group_int, "P1")
        self.assertEqual(data.hall_number, 1)
        self.assertEqual(data.point_group, "1")
        self.assertEqual(data.crystal_system, "triclinic")
        self.assertEqual(data.bravais_lattice, "aP")
        self.assertTrue(data.has_free_wyckoff_parameters)
        self.assertWyckoffGroupsOk(data.conv_system, data.wyckoff_groups_conv)
        self.assertVolumeOk(system, data.conv_system, data.lattice_fit)

    def assertVolumeOk(self, orig_sys, conv_sys, lattice_fit):
        """Check that the Wyckoff groups contain all atoms and are ordered
        """
        n_atoms_orig = len(orig_sys)
        volume_orig = orig_sys.get_volume()
        n_atoms_conv = len(conv_sys)
        volume_conv = np.linalg.det(lattice_fit)
        self.assertTrue(np.allclose(volume_orig/n_atoms_orig, volume_conv/n_atoms_conv, atol=1e-8))

    def assertWyckoffGroupsOk(self, system, wyckoff_groups):
        """Check that the Wyckoff groups contain all atoms and are ordered
        """
        prev_w_index = None
        prev_z = None
        n_atoms = len(system)
        n_atoms_wyckoff = 0
        for (i_w, i_z), group_list in wyckoff_groups.items():

            # Check that the current Wyckoff letter index is greater than
            # previous, if not the atomic number must be greater
            i_w_index = WYCKOFF_LETTER_POSITIONS[i_w]
            if prev_w_index is not None:
                self.assertGreaterEqual(i_w_index, prev_w_index)
                if i_w_index == prev_w_index:
                    self.assertGreater(i_z, prev_z)

            prev_w_index = i_w_index
            prev_z = i_z

            # Gather the number of atoms in eaach group to see that it matches
            # the amount of atoms in the system
            for group in group_list:
                n = len(group.positions)
                n_atoms_wyckoff += n

        self.assertEqual(n_atoms, n_atoms_wyckoff)

    def get_material3d_properties(self, system):
        analyzer = Class3DAnalyzer(system)
        data = dotdict()

        data.space_group_number = analyzer.get_space_group_number()
        data.space_group_int = analyzer.get_space_group_international_short()
        data.hall_symbol = analyzer.get_hall_symbol()
        data.hall_number = analyzer.get_hall_number()
        data.conv_system = analyzer.get_conventional_system()
        data.prim_system = analyzer.get_primitive_system()
        data.translations = analyzer.get_translations()
        data.rotations = analyzer.get_rotations()
        data.origin_shift = analyzer._get_spglib_origin_shift()
        data.choice = analyzer.get_choice()
        data.point_group = analyzer.get_point_group()
        data.crystal_system = analyzer.get_crystal_system()
        data.bravais_lattice = analyzer.get_bravais_lattice()
        data.transformation_matrix = analyzer._get_spglib_transformation_matrix()
        data.wyckoff_original = analyzer.get_wyckoff_letters_original()
        data.wyckoff_conv = analyzer.get_wyckoff_letters_conventional()
        data.wyckoff_groups_conv = analyzer.get_wyckoff_groups_conventional()
        data.prim_wyckoff = analyzer.get_wyckoff_letters_primitive()
        data.prim_equiv = analyzer.get_equivalent_atoms_primitive()
        data.equivalent_original = analyzer.get_equivalent_atoms_original()
        data.equivalent_conv = analyzer.get_equivalent_atoms_conventional()
        data.lattice_fit = analyzer.get_conventional_lattice_fit()
        data.has_free_wyckoff_parameters = analyzer.get_has_free_wyckoff_parameters()
        data.chiral = analyzer.get_is_chiral()

        return data


class NomadTests(unittest.TestCase):
    """
    """
    # def test_fail_1(self):
        # """
        # """
        # system = get_atoms_from_viz("./structures/B2N2.json")
        # # view(system)

        # classifier = Classifier()
        # classification = classifier.classify(system)
        # self.assertIsInstance(classification, Material2D)

    # def test_fail_2(self):
        # """
        # """
        # system = get_atoms_from_viz("./structures/C50+C12H10N2.json")
        # # view(system)

        # classifier = Classifier()
        # classification = classifier.classify(system)
        # self.assertIsInstance(classification, Material2D)

    # def test_fail_3(self):
        # """
        # """
        # system = get_atoms_from_viz("./structures/C12H8+H2N2.json")
        # view(system)

        # classifier = Classifier()
        # classification = classifier.classify(system)
        # self.assertEqual(type(classification), Class2D)

    # def test_fail_4(self):
        # """
        # """
        # system = get_atoms_from_viz("./structures/BN.json")
        # view(system)

        # classifier = Classifier()
        # classification = classifier.classify(system)
        # self.assertIsInstance(classification, Material2D)

    # def test_fail_5(self):
        # """
        # """
        # system = get_atoms_from_viz("./structures/C4B2F4N2.json")
        # view(system)

        # classifier = Classifier()
        # classification = classifier.classify(system)
        # self.assertIsInstance(classification, Material2D)

    # def test_fail_6(self):
        # """
        # """
        # system = get_atoms_from_viz("./structures/Ba6O15+Ba10O25Si12.json")
        # view(system)

        # classifier = Classifier()
        # classification = classifier.classify(system)
        # print(classification)
        # self.assertIsInstance(classification, Material2D)

    # def test_fail_7(self):
        # """
        # """
        # system = get_atoms_from_viz("./structures/Ba8O12+Ba8O28Si12.json")
        # view(system)

        # classifier = Classifier()
        # classification = classifier.classify(system)
        # print(classification)
        # self.assertEqual(type(classification), Class2D)

    # def test_fail_8(self):
        # """
        # """
        # system = get_atoms_from_viz("./structures/Ba15O23+BaO17Si12.json")
        # view(system)
        # # view(system[44:45])

        # classifier = Classifier()
        # classification = classifier.classify(system)
        # print(classification)

    def test_fail_9(self):
        """
        """
        system = get_atoms_from_arch("./structures/PljJz2Ag0G4ZLfJa3lIaNufubZymC.json")
        # view(system)
        # view(system[44:45])

        classifier = Classifier()
        classification = classifier.classify(system)
        print(classification)


if __name__ == '__main__':
    suites = []
    # suites.append(unittest.TestLoader().loadTestsFromTestCase(ExceptionTests))
    # suites.append(unittest.TestLoader().loadTestsFromTestCase(GeometryTests))
    # suites.append(unittest.TestLoader().loadTestsFromTestCase(DimensionalityTests))
    # suites.append(unittest.TestLoader().loadTestsFromTestCase(PeriodicFinderTests))
    # suites.append(unittest.TestLoader().loadTestsFromTestCase(DelaunayTests))
    # suites.append(unittest.TestLoader().loadTestsFromTestCase(AtomTests))
    # suites.append(unittest.TestLoader().loadTestsFromTestCase(Class0DTests))
    # suites.append(unittest.TestLoader().loadTestsFromTestCase(Class1DTests))
    # suites.append(unittest.TestLoader().loadTestsFromTestCase(Material2DTests))
    suites.append(unittest.TestLoader().loadTestsFromTestCase(SurfaceTests))
    # suites.append(unittest.TestLoader().loadTestsFromTestCase(Material3DTests))
    # suites.append(unittest.TestLoader().loadTestsFromTestCase(Material3DAnalyserTests))
    # suites.append(unittest.TestLoader().loadTestsFromTestCase(NomadTests))

    alltests = unittest.TestSuite(suites)
    result = unittest.TextTestRunner(verbosity=0).run(alltests)

    # We need to return a non-zero exit code for the gitlab CI to detect errors
    sys.exit(not result.wasSuccessful())
