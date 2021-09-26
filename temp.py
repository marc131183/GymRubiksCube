class ProjectionRenderer:
    def __init__(
        self, canvas_distance: float, width: int, height: int, bgColor
    ) -> None:
        self.switch = True
        self.last_quadrant = None
        # TODO: need to integrate canvas_distance
        self.canvas_distance = canvas_distance
        pygame.init()
        pygame.font.init()
        self.width, self.height = width, height
        self.dis = pygame.display.set_mode((width, height))
        self.bgColor = bgColor

    # TODO: there's still a problem when u[0] and u[1] are zero, not sure how to fix it yet
    # TODO: integrate canvas distance
    def getCanvasCoordinates(self, pov: np.array, look_point: np.array, objects: list):
        # create a plane that is perpendicular to the view vector and use it as canvas
        u = look_point - pov
        cur_quadrant = getQuadrant(u[0], u[1])
        if cur_quadrant != -1:
            if (
                self.last_quadrant != None
                and max(cur_quadrant, self.last_quadrant)
                - min(cur_quadrant, self.last_quadrant)
                == 2
            ):
                self.switch = not self.switch
            self.last_quadrant = cur_quadrant

        if self.switch:
            v = np.array([u[1], -u[0], 0])
        else:
            v = np.array([-u[1], u[0], 0])
        w = np.cross(u, v)

        v, w = v / np.linalg.norm(v), w / np.linalg.norm(w)
        canvas = Plane(-u / 2, v, w)
        # canvas = Plane(pov + self.canvas_distance * (u / np.linalg.norm(u)), v, w)

        # get Barycentric coordinates for each vertex from every object on the plane
        num_vertices_total = 0
        canvas_coords = []
        for obj in objects:
            canvas_coords.append([])
            for i, vertex in enumerate(obj.vertices):
                canvas_coords[-1].append(
                    (
                        canvas.getBarycentricCoordinates(vertex, pov - vertex),
                        np.linalg.norm(pov - vertex),
                        i,
                    )
                )
                num_vertices_total += 1
            canvas_coords[-1].sort(key=lambda x: x[1])

        return canvas_coords, num_vertices_total

    # TODO: this function is terribly slow, need to find a better/correct way to determine visiblity of faces
    def computeVisibleFaces(
        self, objects: list, canvas_coords, num_vertices_total: int
    ):
        # reset render info from previous render
        for obj in objects:
            for face in obj.faces:
                face._resetCoordsInfo()

        visible_faces = []
        min_distances = [elem[0][1] for elem in canvas_coords]
        current_elem = [0 for elem in canvas_coords]
        for _ in range(num_vertices_total):
            index_of_object_with_min_vertex = min_distances.index(min(min_distances))
            min_vertex = canvas_coords[index_of_object_with_min_vertex][
                current_elem[index_of_object_with_min_vertex]
            ]

            if not isAnyFaceOverVertex(visible_faces, min_vertex[0]):
                for face in objects[index_of_object_with_min_vertex].faces:
                    # set the vertex to visible in each face that contains it
                    if min_vertex[2] in face.vertices:
                        face._coordsInfo[
                            face.vertices.index(min_vertex[2])
                        ] = min_vertex
                    # if new visible face (>= 3 visible vertices), add it to visible_faces
                    if (
                        sum([1 for elem in face._coordsInfo if elem != None]) >= 3
                        and not face in visible_faces
                    ):
                        visible_faces.append(face)

            current_elem[index_of_object_with_min_vertex] += 1
            if (
                current_elem[index_of_object_with_min_vertex]
                > len(canvas_coords[index_of_object_with_min_vertex]) - 1
            ):
                min_distances[index_of_object_with_min_vertex] = np.inf
            else:
                min_distances[index_of_object_with_min_vertex] = canvas_coords[
                    index_of_object_with_min_vertex
                ][current_elem[index_of_object_with_min_vertex]][1]

        return visible_faces

    def render(self, pov: np.array, look_point: np.array, objects: list):
        self.dis.fill(self.bgColor)
        canvas_coordinates, num_vertices_total = self.getCanvasCoordinates(
            pov, look_point, objects
        )
        visible_faces = self.computeVisibleFaces(
            objects, canvas_coordinates, num_vertices_total
        )

        visible_faces = [
            elem for elem in visible_faces if len(elem.getPolygonOfSelf()) == 4
        ]
        # render faces
        for face in visible_faces:
            polygon = face.getPolygonOfSelf()
            pygame.draw.polygon(
                self.dis,
                face.color,
                np.array([self.width / 2, self.height / 2]) + polygon,
            )
            # for vertex in polygon:
            #     pygame.draw.rect(
            #         self.dis,
            #         (255, 0, 0),
            #         [self.width / 2 + vertex[0], self.height / 2 + vertex[1], 5, 5],
            #     )


# speedup of ~7 times compared to the other function in raycastrendering but still too slow
def getColorMap(
    width,
    height,
    bg_color,
    pov,
    canvas_origin,
    canvas_vec1,
    canvas_vec2,
    objects_origin,
    objects_vec1,
    objects_vec2,
    objects_color,
):
    # initialize color map
    rgb_map = np.empty((width, height, 3), dtype=np.int16)
    t = np.arange(height) - height / 2
    canvas_vec2 = np.repeat(canvas_vec2[np.newaxis, :], height, axis=0)
    objects_vec1_repeated = np.repeat(
        objects_vec1[np.newaxis, :, :, np.newaxis], height, axis=0
    )
    objects_vec2_repeated = np.repeat(
        objects_vec2[np.newaxis, :, :, np.newaxis], height, axis=0
    )
    vector_b_repeated = np.repeat(
        (pov - objects_origin)[np.newaxis, :, :, np.newaxis], height, axis=0
    )

    # append background color to object colors at the end for later
    objects_color = np.append(objects_color, bg_color[np.newaxis, :], axis=0)

    for i in range(width):
        # create rays
        # create ray direction (point on canvas - pov)
        ray_direction = (
            canvas_origin
            + canvas_vec1 * (i - width / 2)
            + canvas_vec2 * t[:, np.newaxis]
            - pov
        )
        # now get intersection of ray with objects (rectangles)
        # create matrix that needs to be inverted with shape (height, N, 3, 3), with N = number of squares in world
        ray_direction_repeated = np.repeat(
            ray_direction[:, np.newaxis, :, np.newaxis], len(objects_origin), axis=1
        )
        matrices_a = np.append(
            objects_vec1_repeated,
            np.append(objects_vec2_repeated, -ray_direction_repeated, axis=3),
            axis=3,
        )

        inverse = np.linalg.pinv(matrices_a)
        gamma_phi_t = np.matmul(inverse, vector_b_repeated)

        outside_of_rect = (
            (gamma_phi_t[:, :, 0, 0] < 0)
            | (gamma_phi_t[:, :, 0, 0] > 1)
            | (gamma_phi_t[:, :, 1, 0] < 0)
            | (gamma_phi_t[:, :, 1, 0] > 1)
            | (gamma_phi_t[:, :, 2, 0] <= 0)
        )
        valid_t = np.where(outside_of_rect, np.inf, gamma_phi_t[:, :, 2, 0])
        obj_seen = np.argmin(valid_t, axis=1)
        all_inf = (valid_t == np.inf).all(axis=1)
        color = np.where(all_inf, -1, obj_seen)

        rgb_map[i] = objects_color[color]

    return rgb_map


# TERRIBLY SLOW, DON'T USE
class RaycastRenderer:
    def __init__(
        self, canvas_distance: float, width: int, height: int, bgColor
    ) -> None:
        self.switch = True
        self.last_quadrant = None
        self.canvas_distance = canvas_distance
        pygame.init()
        pygame.font.init()
        self.width, self.height = width, height
        self.dis = pygame.display.set_mode((width, height))
        self.bgColor = bgColor

    def _getColorMap(self, pov: o3.Vector3D, look_point: o3.Vector3D, objects: list):
        u = look_point - pov
        cur_quadrant = getQuadrant(u[0], u[1])
        if cur_quadrant != -1:
            if (
                self.last_quadrant != None
                and max(cur_quadrant, self.last_quadrant)
                - min(cur_quadrant, self.last_quadrant)
                == 2
            ):
                self.switch = not self.switch
            self.last_quadrant = cur_quadrant

        if self.switch:
            v = np.array([u[1], -u[0], 0])
        else:
            v = np.array([-u[1], u[0], 0])
        w = np.cross(u, v)

        v, w = v / np.linalg.norm(v), w / np.linalg.norm(w)
        canvas = Plane(-u / 2, v, w)

        # temp
        origins_obj = np.empty((len(objects) * 6, 3))
        vec1_obj = np.empty((len(objects) * 6, 3))
        vec2_obj = np.empty((len(objects) * 6, 3))
        colors_obj = np.empty((len(objects) * 6, 3))

        i = 0
        for obj in objects:
            for rect in obj.rectangles:
                origins_obj[i] = rect.origin
                vec1_obj[i] = rect.vec1
                vec2_obj[i] = rect.vec2
                colors_obj[i] = rect.color
                i += 1

        return getColorMap(
            self.width,
            self.height,
            self.bgColor,
            pov,
            -u / 2,
            v,
            w,
            origins_obj,
            vec1_obj,
            vec2_obj,
            colors_obj,
        )

        return self._getColorMapHelper(pov, canvas, objects)

    # rather use other function (its much faster)
    def _getColorMapHelper(self, pov: o3.Vector3D, canvas: Plane, objects):
        rgb_map = np.zeros((self.width, self.height, 3))
        for i in range(self.width):
            for j in range(self.height):
                ray = o3.Ray(
                    pov,
                    canvas.convertBarycentricCoordinates(
                        -self.width / 2 + i, -self.height / 2 + j
                    )
                    - pov,
                )
                records = [o3.HitRecord() for _ in range(len(objects))]
                any_hit = False
                for k, obj in enumerate(objects):
                    if obj.hit(ray, records[k]):
                        any_hit = True

                if any_hit:
                    records = [elem for elem in records if elem.t != None]
                    min_record = min(records, key=lambda x: x.t)
                    rgb_map[i, j] = min_record.color
                else:
                    rgb_map[i, j] = self.bgColor

        return rgb_map

    def render(self, pov: o3.Vector3D, look_point: o3.Vector3D, objects: list):
        rgbmap = self._getColorMap(pov, look_point, objects)
        pygame.surfarray.blit_array(self.dis, rgbmap)
