# **Candidate Assignment: Design a Rollout Failure Analysis System**

We care about how you approach the problem, make reasonable assumptions and resolve the ambiguity. You will be evaluated on those dimensions more than if you got to the right solution. We are looking for high-agency, high-ownership people who have a bias for action.

## **Objective**

Design a scalable system that analyzes large numbers of **computer-use agent rollouts**, identifies where and why agents fail, and organizes those failures into a useful and evolving set of failure modes. The goal of this assignment is to evaluate your **system design judgment**: data architecture, distributed processing, LLM-based analysis, taxonomy design, reliability, and cost/scale tradeoffs.

## **Scenario**

We evaluate computer-use agents on thousands of tasks across domains such as marketing, MLOps, customer support, and enterprise operations.

For each task, we may run up to **K rollouts**. A rollout represents one attempt by an agent to complete the task and contains:

* A structured JSON trajectory containing the agent's reasoning-visible state, actions, tool calls, and environment interactions.  
* A sequence of screenshots showing what the agent observed while interacting with the environment.  
* Task metadata and the final evaluation/result.  
* Potentially additional runtime logs.

A typical trajectory is **a few MB in size**.

At our current scale, assume:

* Thousands of distinct tasks.  
* Tens of thousands of trajectories.  
* Multiple rollouts per task.  
* Raw trajectory data stored in **Amazon S3**.  
* New trajectories are continuously generated.

We want to build a system that can answer questions such as:

* Why did an agent fail this task?  
* At what point in the trajectory did the failure occur?  
* Do multiple failed rollouts exhibit the same underlying failure mode?  
* What are the most common failure modes across tasks, domains, or agent versions?  
* Are new failure modes appearing that our existing taxonomy does not capture?

There is **no fixed failure-mode taxonomy**. The system should help bootstrap one and allow it to evolve as more trajectories are analyzed.

## **Your Task**

Design the architecture for a **Rollout Analysis and Failure Mode Analysis System**.

Your design should cover the end-to-end path from raw trajectories in S3 to structured, queryable failure-mode data.

At minimum, discuss:

1. **Ingestion and processing architecture**  
   How trajectories are discovered, queued, processed, retried, versioned, and reprocessed as analysis methods improve.  
2. **Trajectory analysis**  
   How you would analyze JSON actions, screenshots, task context, and outcomes to determine *where* and *why* a rollout failed. You may use LLMs/VLMs as components of the system.  
3. **Failure-mode representation and taxonomy**  
   How failures should be represented, clustered, deduplicated, and assigned to failure modes when the taxonomy is initially unknown.  
4. **Taxonomy evolution**  
   How new failure modes are proposed, reviewed, merged, split, deprecated, or otherwise updated without making historical analyses unusable.  
5. **Storage and retrieval**  
   What data stores and schemas you would use so researchers can query results across trajectories, tasks, model versions, domains, and failure modes.  
6. **Scale, reliability, and cost**  
   Identify likely bottlenecks and explain how your architecture would handle tens of thousands of trajectories today and substantially larger volumes in the future.

## **Deliverable**

Produce a system-design document or diagram explaining your proposed architecture and the major design decisions.

We care more about **clear reasoning and tradeoffs than naming specific technologies**. Where appropriate, state assumptions and explain alternatives you considered.

## **Evaluation**

We will primarily evaluate:

* **Architecture quality:** Is the system scalable, reliable, and operationally reasonable?  
* **Analysis quality:** Does the design produce useful and defensible explanations of agent failures rather than simply assigning labels?  
* **Taxonomy design:** Can failure modes emerge and evolve without creating an unmaintainable classification system?  
* **Data model:** Can researchers trace aggregate findings back to individual tasks, rollouts, and evidence?  
* **Tradeoff reasoning:** Does the candidate identify important cost, latency, accuracy, consistency, and human-vs-automated-analysis tradeoffs?

