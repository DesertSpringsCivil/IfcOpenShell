# IFC 4.4 Voxels (TM27) — Raw Entity Docs

Verbatim `.md` entity documentation from the `tm27` branch (commit `4fe8707`) of
`buildingSMART/IFC4.x-development`, PR #1110. Companion to the synthesized reference.

---

## Source path: `docs/schemas/.../Entities/IfcVoxelGrid.md`

# IfcVoxelGrid

An _IfcVoxelGrid_ representation is a 3D solid shape representation that is compiled of a series of regular blocks placed inside a predefined grid.
## Attributes

### VoxelSizeX
Size of voxels in the X axis.

### VoxelSizeY
Size of voxels in the Y axis.

### VoxelSizeZ
Size of voxels in the Z axis.

### NumberOfVoxelsX
Number of voxels along the X axis.

### NumberOfVoxelsY
Number of voxels along the Y axis.

### NumberOfVoxelsZ
NumberOf voxels along the Z axis.

### Voxels
Indication of voxels on the grid. The array is one-dimensional where values are distributed in the following order:
along X, then Y and finally Z.

## Formal Propositions

---

## Source path: `docs/schemas/.../Entities/IfcVoxelData.md`

# IfcVoxelData

Abstract class representing voxel data values that is assigned to _IfcProduct_ using the relationship _IfcRelAssignsToProduct_ and to a product representation, as _IfcVoxelGrid_, using _Representation_.
The number of values shall correspond to the number of voxels in the voxel grid.
## Attributes

### ValueType
An optional value type used for the values defined in one of the subtypes. Only the names (as labels) of the types available in the _IfcValue_ select type are allowed.

### GridSize
Derived attribute that represents the total number of voxels in the _IfcVoxelGrid_ that is used as the representation for the _IfcVoxelData_ instance.

## Formal Propositions

### IsAssignedToProduct
_IfcVoxelData_ shall have exactly one assignment relationship of type _IfcRelAssignsToProduct_ to a product.

### VoxelGridRepresentation
_IfcVoxelData_ shall have a product definition shape and there shall be exactly one _IfcShapeRepresentation_ in _IfcProductDefinitionShape_._Representations_ that has exactly one geometric item _IfcVoxelGrid_.

### SameRepresentation
The assigned _IfcProduct_ shall have the same shape representation.

---

## Source path: `docs/schemas/.../Entities/IfcComplementaryData.md`

# IfcComplementaryData

A kind of product with the purpose of providing additional raw data, such as observations,  to other products. Complementary data may carry its own representation and shall be related to the main product using _IfcRelAssignsToProduct_.
## Attributes

## Formal Propositions

---

## Source path: `docs/schemas/.../Entities/IfcIntegerVoxelData.md`

# IfcIntegerVoxelData

The voxels represented by integer values.
## Attributes

### ValueData
The values assigned to the voxels as raw integer typed data.

### Unit
An optional unit for the integer values.

### Values
Array of integer values on voxels accessible by the same index as that of the corresponding voxel geometric representation.

## Formal Propositions

---

## Source path: `docs/schemas/.../Entities/IfcRealVoxelData.md`

# IfcRealVoxelData

The voxels represented by real values.
## Attributes

### ValueData
The values assigned to the voxels as raw real typed data.

### Unit
An optional unit for the real values.

### Values
Array of real values on voxels accessible by the same index as that of the corresponding voxel geometric representation.

## Formal Propositions

---

## Source path: `docs/schemas/.../Entities/IfcLabelVoxelData.md`

# IfcLabelVoxelData

The voxels represented by label values.
## Attributes

### ValueData
The values assigned to the voxels as raw label typed data.

### Values
Array of label values on voxels accessible by the same index as that of the corresponding voxel.

## Formal Propositions

---

## Source path: `docs/schemas/.../Entities/IfcLogicalVoxelData.md`

# IfcLogicalVoxelData

The voxels represented by logical values.
## Attributes

### ValueData
The values assigned to the voxels as raw logical typed data.

### Values
Array of logical values on voxels accessible by the same index as that of the corresponding voxel geometric representation.

## Formal Propositions

---

## Source path: `docs/schemas/.../Entities/IfcVectorVoxelData.md`

# IfcVectorVoxelData

The voxels represented by vector values.
## Attributes

### ValueData
The values assigned to the voxels. First x, then y and lastly z.

### Unit
An optional unit for the vector values that overrides the default Magnitude IfcLengthMeasure.

### Values
Array of vector values on voxels accessible by the same index as that of the corresponding voxel geometric representation.

## Formal Propositions

