This project is for autonomous research using claude code agent harnesses, research loops, and sandboxes in order to develop meaningful and opioniated research directions that subagents in docker + VMs can work on.  The goal is to make an easy application that humans can use for autonomous research. We're starting simple and trying to ensure simple RL research tasks can be completed meaningfully and quickly. 

Coding Practices 

1. Keep code modular. Keep code less than 800 lines per file. There should be single source of truth and config files.
2. Create unit tests and e2e tests when necessary. Be systematic in thinking and approaches.
3. Always challenge assumptions. You should verify and spawn adversarial agents to review your work. You should note any important assumptions the human might be making or you might be making.
4. Always ensure you are on a clean branch, and never push on main. 

Directory

meta-planning/docs/plan.md and meta-planning/docs/tasks.md contains important information about the high-level direction of the project. You should be concise when updating these docs. Keep your update either to a checkmark for tasks.md, or 1-3 lines for plan.md. 


