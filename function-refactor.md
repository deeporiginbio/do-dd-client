currently, functions (fast running served tools on the server) are called synchronously and blocking, and results 
are immediately surfaced. for example, this is how we run docking:

```python
protein = Protein(...)
pocket = Pocket(...)

poses = protein.dock(ligand=ligand, pocket=pocket)
# poses is a LigandSet
```

however, under the hood, we call a function in src/functions/docking.py

these functions typically return the function outputs, and other data, e.g.:

```json
{
    "id": "9f3be8f0-434d-4fec-80de-ee068aad4999",
    "createdAt": "2025-12-18T15:07:56.091Z",
    "updatedAt": "2025-12-18T15:09:56.820Z",
    "userInputs": {
        "inputs": {
            "protein_path": "entities/proteins/c32244fd9a1fb1675f69c1d28986ef55867ffd6733b28946d62409cc3f55523f.pdb",
            "ligand_smiles": "Fc1c(-c2cccc3ccccc23)ncc2c(N3C[C@H]4CC[C@@H](C3)N4)nc(OCC34CCCN3CCC4)nc12",
            "box_size": [
                20,
                20,
                20
            ],
            "pocket_center": [
                -13.445080757141113,
                -5.635077953338623,
                13.993667602539062
            ]
        },
        "clusterId": "d638d3cd-833f-476b-87fe-ca6d76e66049"
    },
    "functionOutputs": {
        "binding_energy": -8.99701,
        "pose_score": 0.6846902,
        "sdf_path": "tool-runs/docking/c32244fd9a1fb1675f69c1d28986ef55867ffd6733b28946d62409cc3f55523f/94f7d0c82ed874ec932b06ffda2b9d84f9bc8ab0ae3ec5e28634e8d88b650329.sdf",
        "status": "success",
        "time_taken": 120.211745262146,
        "function_key": "deeporigin.docking",
        "function_version": "0.2.6"
    },
    "status": "Completed",
    "cluster": {
        "id": "d638d3cd-833f-476b-87fe-ca6d76e66049",
        "createdAt": "2024-06-11T16:53:45.922Z",
        "updatedAt": "2025-03-27T20:23:30.842Z",
        "hostname": "https://cluster.us-west-2.dev.deeporigin.io",
        "name": "DeepOrigin Cluster - us-west-2",
        "orgKey": null,
        "enabled": true,
        "status": "healthy"
    },
    "orgKey": "deeporigin",
    "createdBy": "6b96d8f8-0f55-474c-a86c-e09651ba4b20",
    "quotationResult": {
        "anyFailed": false,
        "failedQuotations": [],
        "successfulQuotations": [
            {
                "status": "OK",
                "itemCode": "DO_DOCK",
                "orgId": "deeporigin",
                "qty": 1,
                "priceEach": 0.2,
                "priceTotal": 0.2,
                "pricingRecordType": "regular",
                "pricingRecords": [
                    {
                        "itemKey": "DO_DOCK",
                        "itemName": "Docking",
                        "priceEach": 0.2,
                        "totalPrice": 0.2,
                        "qty": 1,
                        "tierQtyFrom": 0,
                        "tierQtyTo": 0
                    }
                ]
            }
        ]
    },
    "function": {
        "id": "60cef235-0890-4d62-81e8-e2e00b937baf",
        "createdAt": "2025-12-08T15:10:57.947Z",
        "updatedAt": "2025-12-08T15:10:57.947Z",
        "functionManifest": "cf787d83-a8df-4b52-8906-52e25bbd119b",
        "version": "0.2.6",
        "enabled": true,
        "manifestBody": {
            "key": "deeporigin.docking",
            "version": "0.2.6",
            "executor": {
                "name": "deeporigin-docking",
                "path": "/dock",
                "port": {
                    "name": "http1",
                    "port": 8080,
                    "protocol": "TCP"
                },
                "image": "645946264134.dkr.ecr.us-west-2.amazonaws.com/functions/docking:0.2.6",
                "method": "POST",
                "minScale": 1,
                "environment": [
                    {
                        "name": "JULIA_NUM_THREADS",
                        "value": "4"
                    }
                ],
                "timeoutSeconds": 600,
                "containerConcurrency": 1,
                "resourceRequirements": {
                    "cpu": 4,
                    "memory": 4
                },
                "scaleDownDelaySeconds": 60,
                "responseStartTimeoutSeconds": 3600
            },
            "billingCode": "DO_DOCK",
            "inputSchema": {
                "type": "object",
                "required": [
                    "protein_path",
                    "ligand_smiles",
                    "box_size",
                    "pocket_center"
                ],
                "properties": {
                    "box_size": {
                        "type": "array",
                        "items": {
                            "type": "number"
                        },
                        "maxItems": 3,
                        "minItems": 3
                    },
                    "protein_path": {
                        "type": "string"
                    },
                    "ligand_smiles": {
                        "type": "string"
                    },
                    "pocket_center": {
                        "type": "array",
                        "items": {
                            "type": "number"
                        },
                        "maxItems": 3,
                        "minItems": 3
                    }
                },
                "additionalProperties": false
            },
            "functionManifestVersion": "1"
        },
        "billingCode": "DO_DOCK",
        "resourceId": "function-lsw42idrlizz6vaqs8d3f"
    }
}
```

the key feature we want to work on is support for "quoting" a function, i.e, asking for an estimate without actually running it. 

to do so, we have to fundamentally change how functions work. All functions (and class methods that are thin wrappers around functions like `protein.dock`) should return a `results` object, which wraps the JSON above. 

crucially, this behavior should be supported:

```python
results = protein.dock(...) # just run it
results.poses # contains a ligandSet of poses

results = protein.dock(...quote=True)
results.poses # empty, because there's nothing here
results.estimate # a dollar amount for the estiamte, from `quotationResult`
```

This has a very large blast radius:

1. All docs need to be modified to reflect the fact that `results` is returned, and the actual data is contained inside it
2. All docs need to be updated to reflect how to quote functions
3. Jupyter notebooks need to be updated
4. tests have to be updated. possibly, new fixtures needed
5. we need to create a results class. keep it lean. it should inject new attributes on demand (like `poses`) -- only when needed. 