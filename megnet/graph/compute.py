"""
Computing various graph based operations
"""
from __future__ import annotations

import dgl
import numpy as np
import torch


def compute_3body(g):
    """
    Calculate the three body indices from pair atom indices

    Args:
        g: DGL graph

    Returns:
        l_g: DGL graph containing three body information from graph
        triple_bond_indices (np.ndarray): bond indices that form three-body
        n_triple_ij (np.ndarray): number of three-body angles for each bond
        n_triple_i (np.ndarray): number of three-body angles each atom
        n_triple_s (np.ndarray): number of three-body angles for each structure
    """
    bond_atom_indices = g.edges()
    n_atoms = [g.num_nodes()]
    n_atoms_total = np.sum(g.num_nodes())
    first_col = bond_atom_indices[0].numpy().reshape(-1, 1)
    all_indices = np.arange(n_atoms_total).reshape(1, -1)
    n_bond_per_atom = np.count_nonzero(first_col == all_indices, axis=0)
    n_triple_i = n_bond_per_atom * (n_bond_per_atom - 1)
    n_triple = np.sum(n_triple_i)
    n_triple_ij = np.repeat(n_bond_per_atom - 1, n_bond_per_atom)
    triple_bond_indices = np.empty(shape=(n_triple, 2), dtype=np.int32)

    start = 0
    cs = 0
    for i, n in enumerate(n_bond_per_atom):
        if n > 0:
            """
            triple_bond_indices is generated from all pair permutations of atom indices. The
            numpy version below does this with much greater efficiency. The equivalent slow
            code is:

            ```
            for j, k in itertools.permutations(range(n), 2):
                triple_bond_indices[index] = [start + j, start + k]
            ```
            """
            r = np.arange(n)
            x, y = np.meshgrid(r, r)
            c = np.stack([y.ravel(), x.ravel()], axis=1)
            final = c[c[:, 0] != c[:, 1]]
            triple_bond_indices[start : start + (n * (n - 1)), :] = final + cs
            start += n * (n - 1)
            cs += n

    n_triple_s = []
    i = 0
    for n in n_atoms:
        j = i + n
        n_triple_s.append(np.sum(n_triple_i[i:j]))
        i = j

    src_id, dst_id = torch.tensor(triple_bond_indices[:, 0]), torch.tensor(triple_bond_indices[:, 1])
    l_g = dgl.graph((src_id, dst_id))
    l_g.ndata["bond_dist"] = g.edata["bond_dist"]
    l_g.ndata["bond_vec"] = g.edata["bond_vec"]
    l_g.ndata["pbc_offset"] = g.edata["pbc_offset"]
    l_g.ndata["n_triple_ij"] = torch.tensor(n_triple_ij)
    return l_g, triple_bond_indices, n_triple_ij, n_triple_i, np.array(n_triple_s, dtype=np.int32)


def compute_pair_vector_and_distance(g):
    """
    Calculate bond vectors and distances using dgl graphs

    Args:
    g: DGL graph

    Returns:
    bond_vec (torch.tensor): bond distance between two atoms
    bond_dist (torch.tensor): vector from src node to dst node
    """
    atom_pos = g.ndata["pos"]
    bond_vec = torch.zeros(g.num_edges(), 3)
    bond_dist = torch.zeros(g.num_edges())
    for i in range(g.num_edges()):
        bond_vec[i, :] = (
            atom_pos[g.edges()[1][i], :]
            + torch.sum(torch.squeeze(g.edata["pbc_offset"][i][:] * g.edata["lattice"][i][:, None]), dim=0)
            - atom_pos[g.edges()[0][i], :]
        )
    bond_dist = torch.norm(bond_vec, dim=1)
    return bond_vec, bond_dist


def compute_theta_and_phi(edges):
    """
    Calculate bond angle Theta and Phi using dgl graphs

    Args:
    g: DGL graph

    Returns:
    cos_theta: torch.tensor
    phi: torch.tensor
    triple_bond_lengths (torch.tensor):
    """
    vec1 = edges.src["bond_vec"]
    vec2 = edges.dst["bond_vec"]
    cosine_theta = torch.sum(vec1 * vec2, dim=1) / (torch.norm(vec1, dim=1) * torch.norm(vec2, dim=1))
    return {
        "cos_theta": cosine_theta,
        "phi": torch.zeros_like(cosine_theta),
        "triple_bond_lengths": edges.dst["bond_dist"],
    }


def create_line_graph(g, threebody_cutoff: float | None = None):
    """
    Calculate the three body indices from pair atom indices

    Args:
        g: DGL graph
        threebody_cutoff (float): cutoff for three-body interactions

    Returns:
        l_g: DGL graph containing three body information from graph
    """

    bond_atom_indices = g.edges()
    n_bond = bond_atom_indices[0].size(dim=0)
    if n_bond > 0 and threebody_cutoff is not None:
        valid_three_body = g.edata["bond_dist"] <= threebody_cutoff
        np.where(valid_three_body)[0]
        np.arange(n_bond)[valid_three_body]
        src_id_with_three_body = bond_atom_indices[0][valid_three_body]
        dst_id_with_three_body = bond_atom_indices[1][valid_three_body]
        graph_with_three_body = dgl.graph((src_id_with_three_body, dst_id_with_three_body))
        graph_with_three_body.edata["bond_dist"] = g.edata["bond_dist"][valid_three_body]
        graph_with_three_body.edata["bond_vec"] = g.edata["bond_vec"][valid_three_body]
        graph_with_three_body.edata["pbc_offset"] = g.edata["pbc_offset"][valid_three_body]
    else:
        np.arange(n_bond)
    if graph_with_three_body.edata["bond_dist"].size(dim=0) > 0:
        l_g, triple_bond_indices, n_triple_ij, n_triple_i, n_triple_s = compute_3body(graph_with_three_body)
    return l_g