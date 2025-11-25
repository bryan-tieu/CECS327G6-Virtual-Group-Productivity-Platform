import asyncio
import random
from typing import List

# Participant in the 2PC 
# Can either be a person or room
class Participant: 

    def __init__(self, name, fail_rate: float = 0.0, slow: bool = False):
        self.name = name
        self.phase = "focus"
        self.fail_rate = fail_rate
        self.slow = slow

    # Phase 1 of the 2 phase commit
    # Vote to commit or abort 
    async def prepare(self, new_phase):

        # Default delay for processing
        base_delay = random.uniform(0.1, 0.4)

        # Slower node (TESTING PURPOSES)
        if self.slow:
            base_delay += 0.8
        
        await asyncio.sleep(base_delay)

        # Simulating incosistencies in the system for aborting/committing
        if random.random() < self.fail_rate:
            print(f"{self.name} voted ABORT for {new_phase}")
            return False
        
        print(f"{self.name} voted COMMIT for {new_phase}")
        return True 
    
    # Phase 2 of the 2 phase commit
    # Either commit or abort based on votes 
    async def commit(self, new_phase):
        await asyncio.sleep(random.uniform(0.05, 0.2))
        self.phase = new_phase 
        print(f"{self.name} COMMIT: new phase is {self.phase}")

    async def abort(self):
        await asyncio.sleep(random.uniform(0.05, 0.2))
        print(f"{self.name} ABORT: current phase is {self.phase}")

# 2PC Coordinator
class Coordinator:
    
    def __init__(self, participants):
        self.participants = participants
    
    # Run 2 phase 
    async def change_phase(self, new_phase, timeout: float = 1.0):

        print(f"Starting 2PC for new phase {new_phase}")

        prepare_tasks = []

        # Prepare stage 
        for participant in self.participants:
            task = asyncio.wait_for(participant.prepare(new_phase), timeout=timeout)
            prepare_tasks.append(task)

        # Gather results for votes 
        votes = []
        for participant, task in zip(self.participants, prepare_tasks):
            
            try:
                vote = await task
                votes.append(vote)

            except asyncio.TimeoutError:
                print(f"[2PC] TIMEOUT. Waiting for {participant.name}")
                votes.append(False)

            except Exception as e:
                print(f"[2PC] ERROR from {participant.name}. {e}")
                votes.append(False)

        # Change phase based on results 
        # COMMIT 
        if all(votes):
            print("[2PC] ALL COMMIT -> Global Commit")
            await asyncio.gather(*[participant.commit(new_phase) for participant in self.participants])
            print("[2PC] Transaction COMMITTED")
        
        # ABORT 
        else:
            print("[2PC] 1+ ABORT -> Global Abort")
            await asyncio.gather(*[participant.abort() for participant in self.participants])
            print("[2PC] Transaction ABORTED")

        phases = {participant.name: participant.phase for participant in self.participants}
        print(f"[2PC] Phases: {phases}")

# Main program
async def main():
    participants = [
        Participant("Bryan"),
        Participant("Cole"),
        Participant("Tin"),
        Participant("Rebecca"),
        Participant("Emmanuel")
    ]

    coordinator = Coordinator(participants)

    await coordinator.change_phase("Break", timeout=0.7)
    await asyncio.sleep(1)
    await coordinator.change_phase("Focus", timeout=0.7)

if __name__ == "__main__":
    asyncio.run(main())