# Copyright (c) 2014 by California Institute of Technology
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions
# are met:
#
# 1. Redistributions of source code must retain the above copyright
#    notice, this list of conditions and the following disclaimer.
#
# 2. Redistributions in binary form must reproduce the above copyright
#    notice, this list of conditions and the following disclaimer in the
#    documentation and/or other materials provided with the distribution.
#
# 3. Neither the name of the California Institute of Technology nor
#    the names of its contributors may be used to endorse or promote
#    products derived from this software without specific prior
#    written permission.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS
# "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT
# LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS
# FOR A PARTICULAR PURPOSE ARE DISCLAIMED.  IN NO EVENT SHALL CALTECH
# OR THE CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL,
# SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT
# LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF
# USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND
# ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY,
# OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT
# OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF
# SUCH DAMAGE.
#
"""Syntactic manipulation of trees."""
import logging
logger = logging.getLogger(__name__)
import copy
import os
import warnings
import networkx as nx
from tulip.spec.ast import nodes
from tulip.spec import parser


class Tree(nx.DiGraph):
    """Abstract syntax tree as a graph data structure.

    Use this as a scaffold for syntactic manipulation.
    It makes traversals and graph rewriting easier,
    so it is preferred to working directly with the
    recursive AST classes.

    The attribute C{self.root} is the tree's root L{Node}.
    """

    def __init__(self):
        self.root = None
        super(Tree, self).__init__()

    def __repr__(self):
        return repr(self.root)

    def __str__(self):
        # need to override networkx.DiGraph.__str__
        return ('Abstract syntax tree as graph with edges:\n' +
                str([(str(u), str(v))
                    for u, v, d in self.edges_iter(data=True)]))

    @property
    def variables(self):
        """Return the set of variables in C{tree}.

        @rtype: C{set} of L{Var}
        """
        return {u for u in self if isinstance(u, nodes.Var)}

    @classmethod
    def from_recursive_ast(cls, u):
        tree = cls()
        tree.root = u
        tree._recurse(u)
        return tree

    def _recurse(self, u):
        if isinstance(u, nodes.Terminal):
            # necessary this terminal is the root
            self.add_node(u)
        elif isinstance(u, nodes.Operator):
            for i, v in enumerate(u.operands):
                self.add_edge(u, v, pos=i)
                self._recurse(v)
        else:
            raise Exception('unknown node type')
        return u

    def to_recursive_ast(self, u=None):
        if u is None:
            u = self.root
        v = copy.copy(u)
        s = self.succ[u]
        if not s:
            assert isinstance(u, nodes.Terminal)
        else:
            v.operands = [self.to_recursive_ast(x)
                          for _, x, d in sorted(
                              self.out_edges_iter(u, data=True),
                              key=lambda y: y[2]['pos'])]
            assert len(u.operands) == len(v.operands)
        return v

    def add_subtree(self, leaf, tree):
        """Add the C{tree} at node C{nd}.

        @type leaf: L{FOL.Node}

        @param tree: to be added, w/o copying AST nodes.
        @type tree: L{Tree}
        """
        assert not self.successors(leaf)
        for u, v, d in tree.edges_iter(data=True):
            self.add_edge(u, v, pos=d['pos'])
        # replace old leaf with subtree root
        ine = self.in_edges(leaf, data=True)
        if ine:
            assert len(ine) == 1
            ((parent, _, d), ) = ine
            self.add_edge(parent, tree.root, **d)
        else:
            self.root = tree.root
        self.remove_node(leaf)

    def to_pydot(self, detailed=False):
        """Create GraphViz dot string from given AST.

        @type ast: L{ASTNode}
        @rtype: str
        """
        g = ast_to_labeled_graph(self, detailed)
        return nx.to_pydot(g)

    def write(self, filename, detailed=False):
        """Layout AST and save result in PDF file."""
        fname, fext = os.path.splitext(filename)
        fext = fext[1:]  # drop .
        p = self.to_pydot(detailed)
        p.set_ordering('out')
        p.write(filename, format=fext)


def ast_to_labeled_graph(tree, detailed):
    """Convert AST to C{NetworkX.DiGraph} for graphics.

    @param ast: Abstract syntax tree

    @rtype: C{networkx.DiGraph}
    """
    g = nx.DiGraph()
    for u in tree:
        if isinstance(u, nodes.Operator):
            label = u.operator
        elif isinstance(u, nodes.Terminal):
            label = u.value
        else:
            raise TypeError(
                'AST node must be Operator or Terminal, '
                'got instead: {u}'.format(u=u) +
                ', of type: {t}'.format(t=type(u)))
        # show both repr and AST node class in each vertex
        if detailed:
            label += '\n' + str(type(u).__name__)
        g.add_node(id(u), label=label)
    for u, v, d in tree.edges_iter(data=True):
        g.add_edge(id(u), id(v), label=d['pos'])
    return g


def check_for_undefined_identifiers(tree, domains):
    """Check that types in C{tree} are incompatible with C{domains}.

    Raise a C{ValueError} if C{tree} either:

      - contains a variable missing from C{domains}
      - binary operator between variable and
        invalid value for that variable.

    @type tree: L{LTL_AST}

    @param domains: variable definitions:

        C{{'varname': domain}}

        See L{GRSpec} for more details of available domain types.
    @type domains: C{dict}
    """
    for u in tree:
        if isinstance(u, nodes.Var) and u.value not in domains:
            var = u.value
            raise ValueError('undefined variable: ' + str(var) +
                             ', in subformula:\n\t' + str(tree))

        if not isinstance(u, (nodes.Str, nodes.Num)):
            continue

        # is a Const or Num
        var, c = pair_node_to_var(tree, u)

        if isinstance(c, nodes.Str):
            dom = domains[var]

            if not isinstance(dom, list):
                raise Exception(
                    'String constant: ' + str(c) +
                    ', assigned to non-string variable: ' +
                    str(var) + ', whose domain is:\n\t' + str(dom))

            if c.value not in domains[var.value]:
                raise ValueError(
                    'String constant: ' + str(c) +
                    ', is not in the domain of variable: ' + str(var))

        if isinstance(c, nodes.Num):
            dom = domains[var]

            if not isinstance(dom, tuple):
                raise Exception(
                    'Number: ' + str(c) +
                    ', assigned to non-integer variable: ' +
                    str(var) + ', whose domain is:\n\t' + str(dom))

            if not dom[0] <= c.value <= dom[1]:
                raise Exception(
                    'Integer variable: ' + str(var) +
                    ', is assigned the value: ' + str(c) +
                    ', that is out of its range: %d ... %d ' % dom)


def sub_values(tree, var_values):
    """Substitute given values for variables.

    @param tree: AST

    @type var_values: C{dict}

    @return: AST with L{Var} nodes replaces by
        L{Num}, L{Const}, or L{Bool}
    """
    old2new = dict()
    for u in tree.nodes_iter():
        if not isinstance(u, nodes.Var):
            continue
        val = var_values[u.value]
        # instantiate appropriate value type
        if isinstance(val, bool):
            v = nodes.Bool(val)
        elif isinstance(val, int):
            v = nodes.Num(val)
        elif isinstance(val, str):
            v = nodes.Str(val)
        old2new[u] = v
    # replace variable by value
    nx.relabel_nodes(tree, old2new, copy=False)


def sub_constants(tree, var_str2int):
    """Replace string constants by integers.

    To be used for converting arbitrary finite domains
    to integer domains prior to calling gr1c.

    @param const2int: {'varname':['const_val0', ...], ...}
    @type const2int: C{dict} of C{list}
    """
    # logger.info('substitute ints for constants in:\n\t' + str(self))
    old2new = dict()
    for u in tree.nodes_iter():
        if not isinstance(u, nodes.Str):
            continue
        var, op = pair_node_to_var(tree, u)
        # now: c, is the operator and: v, the variable
        str2int = var_str2int[str(var)]
        x = str2int.index(u.value)
        num = nodes.Num(str(x))
        # replace Const with Num
        old2new[u] = num
    nx.relabel_nodes(tree, old2new, copy=False)
    # logger.info('result after substitution:\n\t' + str(self) + '\n')


def sub_bool_with_subtree(tree, bool2subtree):
    """Replace selected Boolean variables with given AST.

    @type tree: L{LTL_AST}

    @param bool2form: map from each Boolean variable to some
        equivalent formula. A subset of Boolean varibles may be used.

        Note that the types of variables in C{tree}
        are defined by C{bool2form}.
    @type bool2form: C{dict} from C{str} to L{Tree}
    """
    for u in tree.nodes():
        if isinstance(u, nodes.Var) and u.value in bool2subtree:
            # tree.write(str(id(tree)) + '_before.png')
            tree.add_subtree(u, bool2subtree[u.value])
            # tree.write(str(id(tree)) + '_after.png')


def pair_node_to_var(tree, c):
    """Find variable under L{Binary} operator above given node.

    First move up from C{nd}, stop at first L{Binary} node.
    Then move down, until first C{Var}.
    This assumes that only L{Unary} operators appear between a
    L{Binary} and its variable and constant operands.

    May be extended in the future, depending on what the
    tools support and is thus needed here.

    @type tree: L{LTL_AST}

    @type L{nd}: L{Const} or L{Num}

    @return: variable, constant
    @rtype: C{(L{Var}, L{Const})}
    """
    # find parent Binary operator
    while True:
        old = c
        c = next(iter(tree.predecessors(c)))
        if isinstance(c, nodes.Binary):
            break
    succ = tree.successors(c)
    v = succ[0] if succ[1] == old else succ[1]
    # go down until var found
    # assuming correct syntax for gr1c
    while True:
        if isinstance(v, nodes.Var):
            break
        v = next(iter(tree.successors(v)))
    # now: b, is the operator and: v, the variable
    return v, c


def infer_constants(formula, variables):
    """Enclose all non-variable names in quotes.

    @param formula: well-formed LTL formula
    @type formula: C{str} or L{LTL_AST}

    @param variables: domains of variables, or only their names.
        If the domains are given, then they are checked
        for ambiguities as for example a variable name
        duplicated as a possible value in the domain of
        a string variable (the same or another).

        If the names are given only, then a warning is raised,
        because ambiguities cannot be checked in that case,
        since they depend on what domains will be used.
    @type variables: C{dict} as accepted by L{GRSpec} or
        container of C{str}

    @return: C{formula} with all string literals not in C{variables}
        enclosed in double quotes
    @rtype: C{str}
    """
    if isinstance(variables, dict):
        for var in variables:
            other_vars = dict(variables)
            other_vars.pop(var)
            _check_var_conflicts({var}, other_vars)
    else:
        logger.error('infer constants does not know the variable domains.')
        warnings.warn(
            'infer_constants can give an incorrect result '
            'depending on the variable domains.\n'
            'If you give the variable domain definitions as dict, '
            'then infer_constants will check for ambiguities.')
    tree = parser.parse(formula)
    old2new = dict()
    for u in tree:
        if not isinstance(u, nodes.Var):
            continue
        if str(u) in variables:
            continue
        # Var (so NAME token) but not a variable
        # turn it into a string constant
        old2new[u] = nodes.Const(str(u))
    nx.relabel_nodes(tree, old2new, copy=False)
    return str(tree)


def _check_var_conflicts(s, variables):
    """Raise exception if set intersects existing variable name, or values.

    Values refers to arbitrary finite data types.

    @param s: set

    @param variables: definitions of variable types
    @type variables: C{dict}
    """
    # check conflicts with variable names
    vars_redefined = {x for x in s if x in variables}
    if vars_redefined:
        raise Exception('Variables redefined: ' + str(vars_redefined))
    # check conflicts with values of arbitrary finite data types
    for var, domain in variables.iteritems():
        # not arbitrary finite type ?
        if not isinstance(domain, list):
            continue
        # var has arbitrary finite type
        conflicting_values = {x for x in s if x in domain}
        if conflicting_values:
            raise Exception('Values redefined: ' + str(conflicting_values))


def check_var_name_conflict(f, varname):
    t = parser.parse(f)
    g = Tree.from_recursive_ast(t)
    v = {x.value for x in g.variables}
    if varname in v:
        raise ValueError('var name "' + varname + '" already used')
    return v


# defunct until further notice
def _flatten(tree, u, to_lang, **kw):
    """Recursively flatten C{tree}.

    @rtype: C{str}
    """
    s = tree.succ[u]
    if not s:
        return to_lang(u, **kw)
    elif len(s) == 2:
        l, r = s
        if s[l]['pos'] == 'right':
            l, r = r, l
        l = _flatten(tree, l, to_lang, **kw)
        r = _flatten(tree, r, to_lang, **kw)
        return to_lang(u, l, r, **kw)
    else:
        (c,) = s
        if u.op == 'X':
            return to_lang(u, _flatten(tree, c, to_lang,
                           prime=True, **kw), **kw)
        else:
            return to_lang(u, _flatten(tree, c, to_lang, **kw), **kw)
