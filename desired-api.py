from deeporigin import projects
# deeporigin.projects is a high level module meant to be user-facing,
# internally, it calls src.platform.client.projects and other modules
# to interact with the data platform. 
df = projects.list()
# returns a dataframe of projects, with columns (only):
# - id
# - name
# - description 
projects.create(name="foo")
# returns None
# makes a new project on data platform
# saves ID to a JSON file ~/.deeporigin/config.json 
# basically this is the "loaded" project
projects.create(name="foo", load=False)
# create a project without "loading" it
# does not touch ~/.deeporigin/config.json 
projects.load("foo")
# this basically sets the ID in ~/.deeporigin/config.json 
projects.current() -> str | None
# prints current project, reading from ~/.deeporigin/config.json 
df = projects.ligands()
# prints out a df of all ligands in the current project. 
# will error if projects.current() is None
# dataframe will contain ID, name, smiles of ligands (and what else?)
df = projects.proteins()
# prints out a df of all proteins in the current project. 
# will error if projects.current() is None
# dataframe will contain ID, name, ?? of proteins (and what else?)
df = projects.executions()
# prints out a df of all executions in the current project. 
# will error if projects.current() is None
# dataframe with execution ID, tool key, tool version, started at, etc. 
ligands = projects.get_ligands()
# returns a ligand set with ligands. 
# arguments to filter can be provided. 
proteins = projects.get_proteins()
# returns a list of Protein objects
# arguments to filter can be provided. 
projects.set_ligands(ligands)
# ligands is a LigandSet object 
# will upload files, set records in data platform, etc.
projects.set_proteins(proteins)
# ligands is a LigandSet object 
# will upload files, set records in data platform, etc.
# implicit project support
# all of the following methods will now use the project ID in communication
# with platform:
LigandSet.sync()
Ligand.sync()
Protein.sync()
Docking.start()
Docking.run() # basically for all tools