import time
import uuid

from deeporigin.drug_discovery import BRD_DATA_DIR, Complex


def run_abfe():
    sim = Complex.from_dir(BRD_DATA_DIR)
    ligand = sim.ligands[6]

    print("Preparing system...")

    _ = sim.prepare(ligand=ligand, padding=1.0)
    print("System prepared")

    sim.abfe.set_test_run(1)

    output_dir_path = f"/tests/{uuid.uuid4()}"
    jobs = sim.abfe.run(ligands=[ligand], quote=True, output_dir_path=output_dir_path)
    job = jobs[0]

    assert job.status == "Quoted", (
        f"Expected job to be quoted, instead got {job.status}"
    )

    print("Job quoted")

    print(job.id)

    job.confirm()

    time.sleep(20)

    # check that job is running
    assert job.status == "Running", (
        f"Expected job to be running, instead got {job.status}"
    )


if __name__ == "__main__":
    run_abfe()
