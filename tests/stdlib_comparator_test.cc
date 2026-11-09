#include <cstdio>
#include <set>

struct Identity {
  int key;
  int payload;
};

namespace std {
template <>
struct less<Identity> {
  bool operator()(const Identity& left, const Identity& right) const {
    return left.key < right.key;
  }
};
}  // namespace std

int main() {
  std::set<Identity> items;
  items.insert({2, 20});
  items.insert({1, 10});
  items.insert({2, 30});
  if (items.size() != 2 || items.find({2, 99})->payload != 20) {
    std::fputs("Specialized comparator lost identity semantics\n", stderr);
    return 1;
  }
  return 0;
}
