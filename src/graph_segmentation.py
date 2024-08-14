# src/graph_segmentation.py
import os
import kimimaro
import networkx as nx
import numpy as np
import matplotlib.pyplot as plt
from sklearn.cluster import KMeans
import scipy.ndimage as ndi

def skeletonize_volume(volume, teasar_params, anisotropy):
    """
    Skeletonize the given volume using Kimimaro.

    Parameters:
    - volume (np.ndarray): The volume to be skeletonized.
    - teasar_params (dict): The parameters for the TEASAR algorithm.
    - anisotropy (tuple): The anisotropy scaling factors.
    - parallel (int): The number of parallel processes to use (default is 1).

    Returns:
    - dict: The skeletonized volume.
    """
    skeletons = kimimaro.skeletonize(
        volume,
        teasar_params=teasar_params,
        anisotropy=anisotropy,
        parallel=1
    )
    return skeletons

def full_graph_generation(skeletons):
    """
    Generate a full graph from the skeletons.

    Parameters:
    - skeletons (dict): Dictionary of skeleton objects.

    Returns:
    - networkx.Graph: The generated graph.
    """
    G = nx.Graph()

    for seg_id, skeleton in skeletons.items():
        vertices = {idx: tuple(vertex) for idx, vertex in enumerate(skeleton.vertices)}
        radii = skeleton.radius
        for vertex_id, vertex in vertices.items():
            G.add_node(vertex, seg_id=seg_id, radius=radii[vertex_id])  # Track which node belongs to which segmentation ID
        for edge in skeleton.edges:
            G.add_edge(vertices[edge[0]], vertices[edge[1]])

    return G

def get_branch_points(G):
    """
    Identify branch points in the graph with radius attribute.

    Parameters:
    - G (networkx.Graph): The graph to analyze.

    Returns:
    - dict: Dictionary of branch points with nodes as keys and (seg_id, radius) as values.
    """
    branch_points = {node: (G.nodes[node]['seg_id'], G.nodes[node]['radius']) for node in G.nodes if len(list(G.neighbors(node))) > 2}
    return branch_points

def get_neighbor_counts(G, branch_points):
    """
    Generate a dictionary with branch point coordinates as keys and the number of their neighbors as values.

    Parameters:
    - G (networkx.Graph): The graph object containing the nodes and edges.
    - branch_points (dict): Dictionary of branch points.

    Returns:
    - dict: A dictionary with branch point coordinates as keys and neighbor counts as values.
    """
    neighbor_counts = {}
    for point in branch_points.keys():
        neighbor_counts[point] = len(list(G.neighbors(point)))
    return neighbor_counts

def get_end_points(G):
    """
    Identify end points in the graph with radius attribute.

    Parameters:
    - G (networkx.Graph): The graph to analyze.

    Returns:
    - dict: Dictionary of end points with nodes as keys and (seg_id, radius) as values.
    """
    end_points = {node: (G.nodes[node]['seg_id'], G.nodes[node]['radius']) for node in G.nodes if len(list(G.neighbors(node))) == 1}
    return end_points

def traverse_path(G, start, previous, branch_points, end_points):
    """
    Trace a path from a starting point to another branch point or an end point.

    Parameters:
    - G (networkx.Graph): The full graph.
    - start (tuple): The starting node.
    - previous (tuple): The previous node in the path.
    - branch_points (dict): Dictionary of branch points.
    - end_points (dict): Dictionary of end points.

    Returns:
    - tuple: The path and the endpoint.
    """
    current = start
    path = [[current, G.nodes[current]['radius']]]

    while True:
        neighbors = list(G.neighbors(current))
        next_node = neighbors[0] if neighbors[1] == previous else neighbors[1]

        if next_node in branch_points:  # Only exclude branch points
            return path, next_node

        previous = current
        current = next_node
        path.append([current, G.nodes[current]['radius']])

        # Keep end_points in path
        if next_node in end_points:
            path.append([next_node, G.nodes[next_node]['radius']])
            return path, next_node

def get_represent_radii(unique_paths):
    """
    Get the representative radius for each branch in unique_paths. Currently consist of medians and means

    Parameters:
    - unique_paths (list of lists): Each element is a list representing a path, where each node is a tuple (node, radius).

    Returns:
    - tuple: Two lists, one containing the median radii and the other containing the mean radii for each branch.
    """
    medians = []
    means = []
    for path in unique_paths:
        radii = [node[1] for node in path]
        medians.append(np.median(radii))
        means.append(np.mean(radii))
    return medians, means

def simplified_graph_generation(G, branch_points, end_points):
    """
    Generate a simplified graph containing only branch points and end points from the full graph.

    Parameters:
    - G (networkx.Graph): The full graph.
    - branch_points (dict): Dictionary of branch points.
    - end_points (dict): Dictionary of end points.

    Returns:
    - tuple: The simplified graph and the list of unique paths.
    """
    simplified_G = nx.Graph()

    # Add branch points and end points to the simplified graph with seg_id
    for node, (seg_id, radius) in branch_points.items():
        simplified_G.add_node(node, seg_id=seg_id, radius=radius)

    for node, (seg_id, radius) in end_points.items():
        simplified_G.add_node(node, seg_id=seg_id, radius=radius)

    paths = []

    # Trace paths starting from each branch point
    for branch_point in branch_points.keys():
        neighbors = list(G.neighbors(branch_point))
        for neighbor in neighbors:
            if neighbor not in branch_points and neighbor not in end_points:
                path, endpoint = traverse_path(G, neighbor, branch_point, branch_points, end_points)
                simplified_G.add_edge(branch_point, endpoint)
                paths.append(path)

    # Remove duplicate paths
    unique_paths = []
    for path in paths:
        path_length = len(path)
        start, end = path[0], path[-1]
        if not any(len(p) == path_length and (p[0] == start and p[-1] == end or p[0] == end and p[-1] == start) for p in unique_paths):
            unique_paths.append(path)

    medians, means = get_represent_radii(unique_paths)
    

    combined = list(zip(medians, means, unique_paths))
    combined_sorted = sorted(combined)
    medians_sorted, means_sorted, unique_paths_sorted = zip(*combined_sorted)
    
    # Convert back to lists (optional, if needed as lists)
    medians_sorted = list(medians_sorted)
    means_sorted = list(means_sorted)
    unique_paths_sorted = list(unique_paths_sorted)
    
    return simplified_G, unique_paths_sorted, medians_sorted, means_sorted

def plot_elbow_curve(rep_rad, max_clusters=10):
    """
    Plot the Elbow curve to help determine the optimal number of clusters.

    Parameters:
    - rep_rad (list): List of representative radii for each branch.
    - max_clusters (int): Maximum number of clusters to consider (default is 10).
    """
    # Set the environment variable to avoid memory leaks
    os.environ["OMP_NUM_THREADS"] = "1"

    inertia = []
    range_n_clusters = list(range(1, max_clusters + 1))
    for n_clusters in range_n_clusters:
        kmeans = KMeans(n_clusters=n_clusters, n_init=10, random_state=42).fit(np.array(rep_rad).reshape(-1, 1))
        inertia.append(kmeans.inertia_)

    # Plot the Elbow curve
    plt.figure()
    plt.plot(range_n_clusters, inertia, marker='o')
    plt.title('Elbow Method for Optimal Number of Clusters')
    plt.xlabel('Number of Clusters')
    plt.ylabel('Inertia')
    plt.show()
    
    # Ask the user to choose the optimal number of clusters
    print("Please choose the optimal number of clusters based on the Elbow plot.")

def cluster_radius(rep_rad, optimal_clusters):
    """
    Cluster the medians based on the chosen number of clusters.

    Parameters:
    - rep_rad (list): List of representative radii for each branch.
    - optimal_clusters (int): The chosen number of clusters.

    Returns:
    - tuple: Cluster labels for each median and the label of the cluster with the largest values.
    """
    # Set the environment variable to avoid memory leaks
    os.environ["OMP_NUM_THREADS"] = "1"

    kmeans = KMeans(n_clusters=optimal_clusters, n_init=10, random_state=42).fit(np.array(rep_rad).reshape(-1, 1))
    labels = kmeans.labels_ + 1  # Add 1 to each label
    
    # Identify the label of the cluster with the largest values
    largest_cluster_label = np.argmax(kmeans.cluster_centers_) + 1
    
    return labels, largest_cluster_label

def relabel_graph_with_branches(G, unique_paths, labels, rep_rad, means):
    """
    Relabel the graph nodes with branch indices and clusters, and calculate branch details.

    Parameters:
    - G (networkx.Graph): The original graph.
    - unique_paths (list): A list of unique paths in the graph, each containing tuples of (coords, radius).
    - labels (list): The cluster labels for the branches.
    - rep_rad (list): The representative radii for each branch.
    - means (list): The mean radii for each branch.

    Returns:
    - networkx.Graph: The graph with nodes relabeled.
    - list: A list of dictionaries, each representing a branch with its details.
    - float: The total length of the skeleton.
    """
    branch_info = []
    total_length = 0

    for index, path in enumerate(unique_paths):
        branch_details = {
            "index": index + 1,  # 1-based index
            "coords": [],
            "representative_radus": rep_rad[index],
            "mean_radius": means[index],
            "label": labels[index],
            "length": 0,
            "mean_volume":0,
            "tortuosity": 0
        }

        previous_node = None
        for node, radius in path:
            G.nodes[node]['label'] = labels[index]
            G.nodes[node]['branch'] = index + 1
            
            branch_details["coords"].append(node)
            
            # If there is a previous node, calculate the length to the current node
            if previous_node is not None:
                branch_details["length"] += np.linalg.norm(np.array(previous_node) - np.array(node))
            
            previous_node = node
        
        # Calculate mean volume using the simplified approximation
        branch_details["mean_volume"] = np.pi * (branch_details["mean_radius"] ** 2) * branch_details["length"]
        
        # Calculate tortuosity
        start_node = np.array(branch_details["coords"][0])
        end_node = np.array(branch_details["coords"][-1])
        euclidean_distance = np.linalg.norm(start_node - end_node)
        actual_length = branch_details["length"]

        branch_details["tortuosity"] = actual_length / euclidean_distance if euclidean_distance != 0 else 0

        # Add the full branch length to the total length after the branch is processed
        total_length += branch_details["length"]
        branch_info.append(branch_details)

    return G, branch_info, total_length

def label_branch_points(G, branch_points):
    """
    Label branch points with the same label as their non-branch_point neighbor with the largest radius.

    Parameters:
    - G (networkx.Graph): The graph containing the skeleton data.
    - branch_points (list): A list of branch point nodes.

    Returns:
    - networkx.Graph: The graph with branch points labeled.
    """
    for branch_point in branch_points:
        neighbors = list(G.neighbors(branch_point))
        
        max_radius = -1
        selected_label = None
        for neighbor in neighbors:
            if neighbor not in branch_points:
                radius = G.nodes[neighbor]['radius']
                if radius > max_radius and 'label' in G.nodes[neighbor]:
                    max_radius = radius
                    selected_label = G.nodes[neighbor]['label']

        if selected_label is not None:
            G.nodes[branch_point]['label'] = selected_label

    return G

def calculate_branching_angles(G, branch_points):
    """
    Calculate the branching angles at each branch point in the graph.

    Parameters:
    - G (networkx.Graph): The graph containing the skeleton data.
    - branch_points (list): A list of branch point nodes.

    Returns:
    - dict: A dictionary with tuples of branch indices as keys and branching angles as values.
    - networkx.Graph: A graph where each node represents a branch, and edges represent connectivity between branches.
    """
    branching_angles = {}
    branch_connectivity_graph = nx.Graph()
    
    for branch_point in branch_points.keys():
        neighbors = list(G.neighbors(branch_point))

        # Calculate vectors from the branch point to each neighbor
        vectors = {}
        for neighbor in neighbors:
            vectors[neighbor] = np.array(neighbor) - np.array(branch_point)

        # Iterate over all unique pairs of neighbors
        for i, neighbor1 in enumerate(neighbors):
            for j, neighbor2 in enumerate(neighbors):
                if i < j:  # Avoid repeating pairs
                    if 'branch' in G.nodes[neighbor1] and 'branch' in G.nodes[neighbor2]:    
                        vector1 = vectors[neighbor1]
                        vector2 = vectors[neighbor2]
    
                        # Calculate the angle between the two vectors
                        cosine_angle = np.dot(vector1, vector2) / (np.linalg.norm(vector1) * np.linalg.norm(vector2))
                        angle = np.arccos(np.clip(cosine_angle, -1.0, 1.0))
                    
                        # Store the angle with the pair of neighbors as the key
                        key = tuple(sorted((G.nodes[neighbor1]['branch'], G.nodes[neighbor2]['branch'])))
                        if key not in branching_angles:
                            branching_angles[key] = []
                        branching_angles[key].append(np.degrees(angle))
                        
                        # Add an edge between the two branches in the connectivity graph
                        branch_connectivity_graph.add_edge(G.nodes[neighbor1]['branch'], G.nodes[neighbor2]['branch'])

                        # Add node attributes to the connectivity graph for each branch
                        branch_connectivity_graph.nodes[G.nodes[neighbor1]['branch']]['label'] = G.nodes[neighbor1]['label']
                        branch_connectivity_graph.nodes[G.nodes[neighbor2]['branch']]['label'] = G.nodes[neighbor2]['label']

    return branching_angles, branch_connectivity_graph

def post_process_branch_labels(G, branch_connectivity_graph, largest_cluster_label, unique_paths):
    """
    Post-process the branch labels to merge small branches sandwiched between two large branches.

    Parameters:
    - G (networkx.Graph): The original graph containing the skeleton data.
    - branch_connectivity_graph (networkx.Graph): The branch connectivity graph.
    - largest_cluster_label (int): The label of the largest cluster of branches.
    - unique_paths (list): A list of unique paths, where each path contains tuples of (coords, radius) for each branch.

    Returns:
    - networkx.Graph: The updated branch connectivity graph.
    - networkx.Graph: The original graph G with updated branch labels.
    """
    branches_to_relabel = set()

    # Identify branches sandwiched by large branches
    for node in branch_connectivity_graph.nodes:
        neighbors = list(branch_connectivity_graph.neighbors(node))
        
        # Check if at least 2 neighbors are part of the largest cluster
        if len(neighbors) >= 2:
            large_neighbors = [
                neighbor for neighbor in neighbors
                if branch_connectivity_graph.nodes[neighbor]['label'] == largest_cluster_label
            ]
            if len(large_neighbors) >= 2:
                branches_to_relabel.add(node)

    # Relabel the identified branches in both graphs
    for branch in branches_to_relabel:
        # Relabel the branch in branch_connectivity_graph
        branch_connectivity_graph.nodes[branch]['label'] = largest_cluster_label
        
        # Relabel all nodes in the corresponding branch in the original graph G using unique_paths
        for coord, _ in unique_paths[branch - 1]:  # Assuming branch is 1-based index
            if 'branch' in G.nodes[coord] and G.nodes[coord]['branch'] == branch:
                G.nodes[coord]['label'] = largest_cluster_label

    return branch_connectivity_graph, G

def calculate_distance_from_largest(branch_connectivity_graph, largest_cluster_label):
    """
    Calculate the distance of each branch from the nearest branch in the largest cluster.

    Parameters:
    - branch_connectivity_graph (networkx.Graph): The graph where nodes represent branches.
    - largest_cluster_label (int): The label of the largest cluster of branches.

    Returns:
    - dict: A dictionary with branch indices as keys and distances as values.
    """
    # Identify nodes (branches) in the largest cluster
    largest_cluster_nodes = [
        node for node, data in branch_connectivity_graph.nodes(data=True)
        if data['label'] == largest_cluster_label
    ]

    # Initialize distances with a large number (infinity)
    distances = {node: float('inf') for node in branch_connectivity_graph.nodes()}

    # Set the distance to 0 for all nodes in the largest cluster
    for node in largest_cluster_nodes:
        distances[node] = 1

    # Use BFS to calculate the shortest distance to the largest cluster
    for node in largest_cluster_nodes:
        for neighbor in nx.bfs_tree(branch_connectivity_graph, source=node):
            # Only update if the current path is shorter
            distances[neighbor] = min(distances[neighbor], distances[node] + 1)
    
    # Find the furthest distance
    max_distance = max(distances.values())
    print(f"The largest distance from a large branch is: {max_distance - 1}")
    
    return distances

def propagate_distances_to_original_graph(G, branch_connectivity_graph, distances):
    """
    Propagate the "distance_from_largest" attribute to the original graph G.

    Parameters:
    - G (networkx.Graph): The original graph containing the skeleton data.
    - branch_connectivity_graph (networkx.Graph): The branch connectivity graph.
    - distances (dict): A dictionary with branch indices as keys and distances as values.

    Returns:
    - networkx.Graph: The original graph G with the "distance_from_largest" attribute added to each node.
    """
    # Iterate through the nodes in the original graph G
    for node in G.nodes:
        if 'branch' in G.nodes[node]:
            branch_index = G.nodes[node]['branch']
            if branch_index in distances:
                G.nodes[node]['dist_from_largest'] = distances[branch_index]
            else:
                G.nodes[node]['dist_from_largest'] = -1

    return G

def get_ellipsoid_surface(radius, scaling_factors):
    """
    Generate the surface voxels of an ellipsoid given a radius and scaling factors.

    Parameters:
    - radius (int): The radius of the ellipsoid.
    - scaling_factors (tuple): The scaling factors (sz, sy, sx) for the z, y, x axes.

    Returns:
    - np.ndarray: An array of shape (N, 3) with the coordinates of the surface voxels.
    """
    sz, sy, sx = scaling_factors
    theta = np.linspace(0, np.pi, 100)
    phi = np.linspace(0, 2 * np.pi, 100)
    theta, phi = np.meshgrid(theta, phi)

    # Parametric equations for the ellipsoid
    x = radius * np.sin(theta) * np.cos(phi) / sx
    y = radius * np.sin(theta) * np.sin(phi) / sy
    z = radius * np.cos(theta) / sz

    # Flatten and combine coordinates
    coords = np.vstack((z.ravel(), y.ravel(), x.ravel())).T
    return coords

def segment_volume(filtered_array, G, voxel_size, attribute='label'):
    """
    Segment the volume using distance transforming with a specified node attribute.

    Parameters:
    - filtered_array (np.ndarray): The filtered array to be segmented.
    - G (networkx.Graph): The graph containing the skeleton data with the specified attribute.
    - voxel_size (tuple): The anisotropy scaling factors (sz, sy, sx).
    - attribute (str): The node attribute to segment by (default is 'label').

    Returns:
    - tuple: The segmented volume and the unique labels.
    """
    
    if attribute == 'radius':
        filtered_array = filtered_array.astype(float)
    
    # Create a 3D volume for the skeleton points with the same shape as `filtered_array`
    category_indices = np.zeros_like(filtered_array)
    
    # Set to store unique categories
    unique_labels = set()
    
    # Iterate through the nodes in the graph
    for idx, node in enumerate(G.nodes):
        if attribute in G.nodes[node]:  # Ensure the node has the specified attribute
            category = G.nodes[node][attribute]
            radius = G.nodes[node]['radius']  # Use the node's radius attribute

            # Get the surface voxels of the ellipsoid
            surface_voxels = get_ellipsoid_surface(radius, voxel_size)

            # Adjust the node coordinates to match the anisotropic space
            adjusted_node = np.array([int(coord / scale) for coord, scale in zip(node, voxel_size)])
            adjusted_surface_voxels = (surface_voxels + adjusted_node).astype(int)

            # Set the surface voxels in category_indices using advanced indexing
            z_coords, y_coords, x_coords = adjusted_surface_voxels.T
            valid_mask = (
                (z_coords >= 0) & (z_coords < filtered_array.shape[0]) &
                (y_coords >= 0) & (y_coords < filtered_array.shape[1]) &
                (x_coords >= 0) & (x_coords < filtered_array.shape[2])
            )
            category_indices[z_coords[valid_mask], y_coords[valid_mask], x_coords[valid_mask]] = category
            unique_labels.add(category)

    # Create a mask for the foreground voxels in category_indices
    foreground_mask = category_indices != 0

    # Compute distance transform from foreground to non-foreground regions
    _, indices = ndi.distance_transform_cdt(~foreground_mask, return_indices=True)

    # Map each non-zero voxel to the nearest category using the indices
    non_zero_mask = filtered_array != 0
    filtered_array[non_zero_mask] = category_indices[tuple(indices[:, non_zero_mask])]

    # Extract unique labels present in the segmented volume
    skel_label = sorted(unique_labels)

    return filtered_array, skel_label